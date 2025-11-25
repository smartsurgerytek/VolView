/* eslint-disable no-useless-constructor */
/* eslint-disable class-methods-use-this */
/* eslint-disable no-continue */
/* eslint-disable no-restricted-syntax */

import JSZip from "jszip";
import dcmjs from "dcmjs";
import * as dicomParser from "dicom-parser";
import { get } from "http";

export interface DicomImageInfo {
  sopInstanceUID: string;
  seriesInstanceUID: string;
  sopClassUID: string;
  imagePosition: number[];
  imageOrientation: number[];
  pixelSpacing: number[];
}

export interface ParsedAnnotation {
  shape: "line" | "rectangle";
  sopInstanceUID: string;
  coordinates: number[]; // [x1,y1,x2,y2]
}

export interface ZipParseResult {
  images: Record<string, DicomImageInfo>;
  annotations: ParsedAnnotation[];
}

// ------------------------------------------------------------------
//  GEOMETRY HELPERS
// ------------------------------------------------------------------

function distance3D(a: number[], b: number[]): number {
  return Math.sqrt(
    (a[0] - b[0]) ** 2 +
      (a[1] - b[1]) ** 2 +
      (a[2] - b[2]) ** 2
  );
}

function pixelToPatient(
  row: number,
  col: number,
  imagePosition: number[],
  imageOrientation: number[],
  pixelSpacing: number[]
): number[] {
  const rowDir = imageOrientation.slice(0, 3);
  const colDir = imageOrientation.slice(3, 6);

  const [rowSpacing, colSpacing] = pixelSpacing;

  return [
    imagePosition[0] + row * rowSpacing * rowDir[0] + col * colSpacing * colDir[0],
    imagePosition[1] + row * rowSpacing * rowDir[1] + col * colSpacing * colDir[1],
    imagePosition[2] + row * rowSpacing * rowDir[2] + col * colSpacing * colDir[2],
  ];
}

// keep: rectangle → polyline
export function rectangleToPolyline(coords: number[]): [number, number][] {
  if (coords.length !== 4) {
    throw new Error("Rectangle needs 4 coordinates: [x1,y1,x2,y2]");
  }

  const [x1, y1, x2, y2] = coords;

  const xMin = Math.min(x1, x2);
  const xMax = Math.max(x1, x2);
  const yMin = Math.min(y1, y2);
  const yMax = Math.max(y1, y2);

  return [
    [xMin, yMin],
    [xMax, yMin],
    [xMax, yMax],
    [xMin, yMax],
    [xMin, yMin],
  ];
}

const { DicomMessage } = dcmjs.data;

// ------------------------------------------------------------------
//  ZIP PARSING
// ------------------------------------------------------------------
type ManifestType = {
  datasets: { id: string; dataSourceId: number }[];
  dataSources: { id: number; type: string; fileId?: number; sources?: number[] }[];
  datasetFilePath: Record<string, string>;
};

/**
 * Given:
 *   - VolView imageID (datasetId)
 *   - VolView manifest JSON
 *   - dicomPath-to-SOPInstanceUID map
 *
 * Returns:
 *   SOPInstanceUID for the referenced image
 */
export function getSOPInstanceFromImageID(
  imageID: string,
  manifest: ManifestType,
  dicomToSopMap: Record<string, string>
): string | undefined {
  // 1. Find dataset by imageID (dataset.id === imageID)
  const dataset = manifest.datasets.find(d => d.id === imageID);
  if (!dataset) return undefined;

  const dataSourceId = dataset.dataSourceId;

  // 2. Find dataSource entry by its ID
  const dataSource = manifest.dataSources.find(ds => ds.id === dataSourceId);
  if (!dataSource) return undefined;

  // Case A: collection → points to another dataSource
  let finalFileId: number | undefined = undefined;

  if (dataSource.type === "collection") {
    const src = manifest.dataSources.find(ds => ds.id === dataSource.sources?.[0]);
    finalFileId = src?.fileId;
  }

  // Case B: direct file entry
  if (dataSource.type === "file") {
    finalFileId = dataSource.fileId;
  }

  if (!finalFileId) return undefined;

  // 3. Use fileId to find DICOM file path
  const dicomPath = manifest.datasetFilePath[String(finalFileId)];
  if (!dicomPath) return undefined;

  // 4. Lookup SOPInstanceUID from your dictionary
  return dicomToSopMap[dicomPath];
}

export async function parseVolViewZip(zipBlob: Blob): Promise<ZipParseResult> {
  const zip = await JSZip.loadAsync(zipBlob);

  // ------------------------------------------
  // 1. MANIFEST.JSON
  // ------------------------------------------
  const manifestEntry = zip.file("manifest.json");
  if (!manifestEntry) throw new Error("manifest.json not found in ZIP");

  const manifestText = await manifestEntry.async("string");
  const manifest = JSON.parse(manifestText);

  const datasetFilePath = manifest.datasetFilePath || {};

  // ------------------------------------------
  // 2. EXTRACT DICOM METADATA
  // ------------------------------------------
  const dicomInfoMap: Record<string, DicomImageInfo> = {};
  const dicomPathToSOP: Record<string, string> = {};

  for (const fileId of Object.keys(datasetFilePath)) {
    const dicomPath = datasetFilePath[fileId];
    const file = zip.file(dicomPath);
    if (!file) continue;

    const dicomBytes = await file.async("arraybuffer");

    try {
        const dataSet = dicomParser.parseDicom(new Uint8Array(dicomBytes));
        
        const sopInstanceUID = dataSet.string('x00080018');
        const seriesInstanceUID = dataSet.string('x0020000e');
        const sopClassUID = dataSet.string('x00080016');

        dicomPathToSOP[dicomPath] = sopInstanceUID;
        
        // Helper function to parse DICOM array strings
        const parseDicomArray = (tag, defaultValue) => {
            const value = dataSet.string(tag);
            if (!value) return defaultValue;
            return value.split('\\').map(Number);
        };

        dicomInfoMap[sopInstanceUID] = {
            sopInstanceUID,
            seriesInstanceUID,
            sopClassUID,
            imagePosition: parseDicomArray('x00200032', [0, 0, 0]),
            imageOrientation: parseDicomArray('x00200037', [1, 0, 0, 0, 1, 0]),
            pixelSpacing: parseDicomArray('x00280030', [1, 1]),
        };
    } catch (error) {
        console.error(`Error parsing DICOM file ${dicomPath}:`, error);
        continue;
    }
  }

  // ------------------------------------------
  // 3. PARSE RULERS & RECTANGLES
  // ------------------------------------------
  const annotations: ParsedAnnotation[] = [];

  // lines
  const rulers = manifest.tools?.rulers?.tools ?? [];
  for (const r of rulers) {
    annotations.push({
      shape: "line",
      sopInstanceUID: getSOPInstanceFromImageID(r.imageID, manifest, dicomPathToSOP) || "",
      coordinates: [r.firstPoint[0], r.firstPoint[1], r.secondPoint[0], r.secondPoint[1]],
    });
  }

  // rectangles
  const rects = manifest.tools?.rectangles?.tools ?? [];
  for (const rect of rects) {
    // const rectangleCoordinates = rectangleToPolyline(coordinates).flat();
    annotations.push({
      shape: "rectangle",
      sopInstanceUID: getSOPInstanceFromImageID(rect.imageID, manifest, dicomPathToSOP) || "",
      coordinates: [rect.firstPoint[0], rect.firstPoint[1], rect.secondPoint[0], rect.secondPoint[1]]
    });
  }

  return {
    images: dicomInfoMap,
    annotations,
  };
}

// ------------------------------------------------------------------
//  DOMAIN DTOs
// ------------------------------------------------------------------

export type Shape = "line" | "rectangle";

export interface Annotation {
  shape: Shape;
  measurementName: string;
  measurementValue?: number | null;

  sopClassUID: string;
  seriesInstanceUID: string;
  sopInstanceUID: string;

  coordinates: number[];
}

export interface Manifest {
  annotations: Annotation[];

  studyInstanceUID: string;
  studyId: string;

  patientName: string;
  patientId: string;
  patientBirthDate: string;
  patientSex: string;

  manifestJson: string;
  createdBy: string;
  createdAt: string;
  sopClassUid: string;
}

// ------------------------------------------------------------------
//  MEASUREMENT CALCULATOR
// ------------------------------------------------------------------

export class MeasurementCalculator {
  constructor(private images: Record<string, DicomImageInfo>) {}

  private meta(sop: string): DicomImageInfo {
    const m = this.images[sop];
    if (!m) throw new Error(`No metadata found for SOPInstanceUID ${sop}`);
    return m;
  }

  // ---------------------------------------------------------
  // LINE LENGTH (true 3D)
  // ---------------------------------------------------------
  computeLineLength(annotation: ParsedAnnotation): number {
    const meta = this.meta(annotation.sopInstanceUID);
    const [x1, y1, x2, y2] = annotation.coordinates;

    const A = pixelToPatient(
      y1,
      x1,
      meta.imagePosition,
      meta.imageOrientation,
      meta.pixelSpacing
    );

    const B = pixelToPatient(
      y2,
      x2,
      meta.imagePosition,
      meta.imageOrientation,
      meta.pixelSpacing
    );

    return distance3D(A, B);
  }

  // ---------------------------------------------------------
  // RECTANGLE CONVERSION
  // ---------------------------------------------------------
  convertRectangle(annotation: ParsedAnnotation): [number, number][] {
    return rectangleToPolyline(annotation.coordinates);
  }

  // ---------------------------------------------------------
  // RECTANGLE PERIMETER (2D pixel space)
  // ---------------------------------------------------------
  computeRectanglePerimeter(coords: [number, number, number, number]): number {
    const [x1, y1, x2, y2] = coords;
    const width = Math.abs(x2 - x1);
    const height = Math.abs(y2 - y1);
    return 2 * (width + height);
  }

  // ---------------------------------------------------------
  // RECTANGLE AREA (2D pixel space)
  // ---------------------------------------------------------
  computeRectangleArea(coords: [number, number, number, number], sopInstanceUID): number {
    const metaData = this.meta(sopInstanceUID);
    const [x1, y1, x2, y2] = coords;

    const A = pixelToPatient(
      y1,
      x1,
      metaData.imagePosition,
      metaData.imageOrientation,
      metaData.pixelSpacing
    );

    const B = pixelToPatient(
      y2,
      x2,
      metaData.imagePosition,
      metaData.imageOrientation,
      metaData.pixelSpacing
    );

    const width = Math.abs(A[0] - B[0]);
    const height = Math.abs(A[1] - B[1]);
    return width * height;
  }
}

export async function createManifest(zipBlob: Blob): Promise<Manifest> {
  const { images, annotations } = await parseVolViewZip(zipBlob);
  const measurementCalculator = new MeasurementCalculator(images);

  const manifestAnnotations: Annotation[] = [];

  for (const ann of annotations) {
    const meta = images[ann.sopInstanceUID];

    let measurementValue: number | null = null;

    if (ann.shape === "line") {
      measurementValue = measurementCalculator.computeLineLength(ann);
    } else if (ann.shape === "rectangle") {
      measurementValue = measurementCalculator.computeRectangleArea(ann.coordinates as [number, number, number, number], ann.sopInstanceUID);
      ann.coordinates = rectangleToPolyline(ann.coordinates as [number, number, number, number]).flat();
    }

    manifestAnnotations.push({
      shape: ann.shape,
      measurementName: ann.shape === "line" ? "Length" : "Area",
      measurementValue,

      sopClassUID: meta.sopClassUID,
      seriesInstanceUID: meta.seriesInstanceUID,
      sopInstanceUID: meta.sopInstanceUID,

      coordinates: ann.coordinates,
    });
  }

  const arrayBuffer = await zipBlob.arrayBuffer();
  const zip = await JSZip.loadAsync(arrayBuffer);

  const manifestFile = zip.file("manifest.json");
  if (!manifestFile) throw new Error("manifest.json not found in zip");

  const text = await manifestFile.async("text");
  // Find the first DICOM file inside data/
  const firstEntry = Object.values(zip.files)
    .find(f => !f.dir && f.name.startsWith("data/"));

  if (!firstEntry) {
    throw new Error("No DICOM files found in ZIP under data/ folder.");
  }

  // Parse the first DICOM file
  const dicomBytes = await firstEntry.async("arraybuffer");
  const dataSet = dicomParser.parseDicom(new Uint8Array(dicomBytes));
  // const dicomData = DicomMessage.readFile(new Uint8Array(dicomBytes));
  // const dataSet = dcmjs.data.DicomMetaDictionary.naturalizeDataset(dicomData.dict);

  // Extract key metadata
  return {
    studyInstanceUID: dataSet.string('x0020000d'),
    studyId: dataSet.string('x00200010'),
    // seriesInstanceUID: dataSet.string("x0020000e"),
    patientName: dataSet.string('x00100010'),
    patientId: dataSet.string('x00100020'),
    patientSex: dataSet.string('x00100040'),
    patientBirthDate: dataSet.string('x00100030'),
    // modality: dataSet.string("x00080060"),
    manifestJson: text,
    createdBy: "VolView Application",
    createdAt: new Date().toISOString(),
    sopClassUid: dataSet.string('x00080016'),
    annotations: manifestAnnotations,
  };
}