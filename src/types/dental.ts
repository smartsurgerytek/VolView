import type { Vector3 } from '@kitware/vtk.js/types';

/**
 * Represents a pair of TRL and CAL measurement points.
 */
export interface TRLCALPair {
  trl: {
    firstPoint: Vector3 | number[];
    secondPoint: Vector3 | number[];
  };
  cal: {
    firstPoint: Vector3 | number[];
    secondPoint: Vector3 | number[];
  };
}

/**
 * Represents measurement data for a single tooth.
 */
export interface ToothData {
  centerPosition?: Vector3 | number[];
  trlCalPairs?: TRLCALPair[];
}

/**
 * Inference data structure containing all tooth measurements.
 */
export interface InferenceData {
  teeth?: Record<string, ToothData>;
}
