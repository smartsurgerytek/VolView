import { useCurrentImage } from "@/src/composables/useCurrentImage";
import { Tags } from "@/src/core/dicomTags";
import DicomChunkImage from "@/src/core/streaming/dicomChunkImage";
import { useRulerStore } from "./rulers";
import { useImageCacheStore } from "../image-cache";

const { VITE_FASTAPI_URL } = import.meta.env;

const REQUIRED_LABELS = [
    { name: 'stage 0', color: '#6df24cff', strokeWidth: 3, stageKey: '0' },
    { name: 'stage 1', color: '#e1f24cff', strokeWidth: 3, stageKey: 'I' },
    { name: 'stage 2', color: '#4cbdf2ff', strokeWidth: 3, stageKey: 'II' },
    { name: 'stage 3', color: '#f2bd4cff', strokeWidth: 3, stageKey: 'III' },
    { name: 'TRL', color: '#574cf2ff', strokeWidth: 3, stageKey: 'trl' },
];

interface ApiRuler {
    stage: string;
    firstPoint: [number, number, number];
    secondPoint: [number, number, number];
    imageID: string;
}

interface ApiResponse {
    data: ApiRuler[];
}

interface DicomImageData {
    pixelSpacing: [number, number];
    studyInstanceUID: string;
    seriesInstanceUID: string;
    sopInstanceUID: string;
}

function getDicomImageData(currentImageID: string): DicomImageData {
    const imageCacheStore = useImageCacheStore();

    // default value
    const data = {
        pixelSpacing: [1, 1] as [number, number],
        studyInstanceUID: "",
        seriesInstanceUID: "",
        sopInstanceUID: "",
    };

    const image = imageCacheStore.imageById[currentImageID];

    if (!(image instanceof DicomChunkImage)) {
        return data;
    }

    const metaPairs = image.getDicomMetadata();
    if (!metaPairs) {
        return data;
    }

    try {
        const metadata = Object.fromEntries(metaPairs);

        // --- 1. get UIDs ---
        data.studyInstanceUID = metadata[Tags.StudyInstanceUID] || "";
        data.seriesInstanceUID = metadata[Tags.SeriesInstanceUID] || "";
        data.sopInstanceUID = metadata[Tags.SOPInstanceUID] || "";

        // --- 2. get PixelSpacing ---
        const pixelSpacingStr = metadata[Tags.PixelSpacing] as string | undefined;

        if (pixelSpacingStr) {
            const parts = pixelSpacingStr.split('\\');
            if (parts.length >= 2) {
                const colSpacing = parseFloat(parts[1]); // X 
                const rowSpacing = parseFloat(parts[0]); // Y 

                if (!Number.isNaN(colSpacing)) {
                    data.pixelSpacing[0] = colSpacing; // X
                }
                if (!Number.isNaN(rowSpacing)) {
                    data.pixelSpacing[1] = rowSpacing; // Y
                }
            }
        }

    } catch (error) {
        console.error("Error parsing DICOM metadata:", error);
    }

    return data;
}

async function fetchApiRulers(currentImageID: string, dicomData: DicomImageData): Promise<ApiRuler[]> {
    const {
        pixelSpacing,
        studyInstanceUID,
        seriesInstanceUID,
        sopInstanceUID,
    } = dicomData;

    const response = await fetch(`${VITE_FASTAPI_URL}/get_measurement`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            StudyInstanceUID: studyInstanceUID,
            SeriesInstanceUID: seriesInstanceUID,
            SopInstanceUID: sopInstanceUID,
            ImageID: currentImageID,
            ScaleX: pixelSpacing[0],
            ScaleY: pixelSpacing[1],
        }),
    });

    if (!response.ok) {
        throw new Error(`Server error: ${response.statusText}`);
    }

    const responseData = await response.json() as ApiResponse;
    return responseData.data;
}

function prepareLabelMap(): {
    stageToLabelID: Record<string, string>;
    fallbackLabelId: string;
} {
    const rulerStore = useRulerStore();

    // 1. create a labelName -> id table
    const nameToIdMap = new Map<string, string>();
    // for (const [id, label] of Object.entries(rulerStore.labels)) {
    //     nameToIdMap.set((label as any).labelName, id);
    // }

    Object.entries(rulerStore.labels).forEach(([id, label]) => {
        nameToIdMap.set((label as any).labelName, id);
    });

    const stageToLabelID: Record<string, string> = {};
    let fallbackLabelId = '';

    // 2. check is REQUIRED_LABELS is already existed
    REQUIRED_LABELS.forEach(labelInfo => {
        let labelId = nameToIdMap.get(labelInfo.name);

        if (!labelId) {
            labelId = rulerStore.addLabel({
                labelName: labelInfo.name,
                color: labelInfo.color,
                strokeWidth: labelInfo.strokeWidth,
            });
        }

        stageToLabelID[labelInfo.stageKey] = labelId;

        if (labelInfo.stageKey === '0') {
            fallbackLabelId = labelId;
        }
    });

    return { stageToLabelID, fallbackLabelId };
}

export async function getMeasurement() {

    const rulerStore = useRulerStore();
    const currentImageID = useCurrentImage()?.currentImageID?.value;
    if (!currentImageID)
        return

    try {
        const dicomData = getDicomImageData(currentImageID);

        const rulers = await fetchApiRulers(currentImageID, dicomData);

        const { stageToLabelID, fallbackLabelId } = prepareLabelMap();

        rulers.forEach(ruler => {
            const label = stageToLabelID[ruler.stage] || fallbackLabelId;

            rulerStore.addRuler({
                label,
                firstPoint: ruler.firstPoint,
                secondPoint: ruler.secondPoint,
                imageID: ruler.imageID,
                name: 'Ruler',
                slice: 0,
                placing: false,
                frameOfReference: {
                    planeNormal: [0, 0, 1],
                    planeOrigin: [0, 0, 0]
                }
            });
        });

    }
    catch (error) {
        console.error("Failed to get measurements:", error);
    }
}

