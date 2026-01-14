import { Vector3 } from "@kitware/vtk.js/types";

export interface DentalLine {
  id: string;
  type: 'CAL' | 'TRL';
  startPoint: Vector3;
  endPoint: Vector3;
  toothId: string;
  pairId: string;
}

export interface ToothData {
  id: string;
  centerPoint: Vector3;
  lines: DentalLine[];
  trlCalPairs: Array<{
    trl: DentalLine;
    cal: DentalLine;
    abld: number;
  }>;
}