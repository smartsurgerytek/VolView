import { createEventHook } from '@vueuse/core';
import { VtkViewApi } from '@/src/types/vtk-types';
import { Vector3 } from '@kitware/vtk.js/types';
import { vec3 } from 'gl-matrix';

// Event hooks for image transformation operations
const flipHorizontalEvent = createEventHook<void>();
const flipVerticalEvent = createEventHook<void>();
const rotateRightEvent = createEventHook<void>();
const rotateLeftEvent = createEventHook<void>();

/**
 * Hook to subscribe to image transformation events
 * Should be used by view components to respond to transform operations
 */
export function useImageTransformEvents() {
  return {
    onFlipHorizontal: flipHorizontalEvent.on,
    onFlipVertical: flipVerticalEvent.on,
    onRotateRight: rotateRightEvent.on,
    onRotateLeft: rotateLeftEvent.on,
  };
}

/**
 * Composable for image transformation operations (flip and rotate)
 * Provides functions to trigger transformations and utilities to apply them to views
 */
export function useImageTransform() {
  /**
   * Triggers a horizontal flip on all active views
   */
  function flipHorizontal() {
    flipHorizontalEvent.trigger();
  }

  /**
   * Triggers a vertical flip on all active views
   */
  function flipVertical() {
    flipVerticalEvent.trigger();
  }

  /**
   * Triggers a 90-degree clockwise rotation on all active views
   */
  function rotateRight() {
    rotateRightEvent.trigger();
  }

  /**
   * Triggers a 90-degree counter-clockwise rotation on all active views
   */
  function rotateLeft() {
    rotateLeftEvent.trigger();
  }

  return {
    flipHorizontal,
    flipVertical,
    rotateRight,
    rotateLeft,
  };
}

/**
 * Applies a horizontal flip to a specific view (left-right flip)
 */
export function applyFlipHorizontal(view: VtkViewApi) {
  const camera = view.renderer.getActiveCamera();

  // Get current camera state
  const viewUp = camera.getViewUp() as Vector3;
  const directionOfProjection = camera.getDirectionOfProjection() as Vector3;

  // Calculate the right vector (horizontal axis)
  const right = vec3.create();
  vec3.cross(right, directionOfProjection, viewUp);
  vec3.normalize(right, right);

  // To flip horizontally (left-right), we need to negate the right vector
  // This is achieved by rotating 180 degrees around the vertical (viewUp) axis
  const flippedRight = vec3.negate(vec3.create(), right) as Vector3;

  // Recalculate direction to point in the same general direction but flipped horizontally
  const newDirection = vec3.create();
  vec3.cross(newDirection, viewUp, flippedRight);
  vec3.normalize(newDirection, newDirection);

  // Update camera position to maintain distance but with new direction
  const focalPoint = camera.getFocalPoint() as Vector3;
  const position = camera.getPosition() as Vector3;
  const distance = vec3.distance(position, focalPoint);

  const newPosition = vec3.create();
  vec3.scaleAndAdd(newPosition, focalPoint, newDirection, -distance);

  camera.setPosition(...(newPosition as Vector3));
  camera.setFocalPoint(...focalPoint);
  camera.setViewUp(...viewUp);

  view.renderWindow.render();
}

/**
 * Applies a vertical flip to a specific view (top-bottom flip)
 */
export function applyFlipVertical(view: VtkViewApi) {
  const camera = view.renderer.getActiveCamera();

  // Get current camera state
  const position = camera.getPosition() as Vector3;
  const focalPoint = camera.getFocalPoint() as Vector3;
  const viewUp = camera.getViewUp() as Vector3;
  const directionOfProjection = camera.getDirectionOfProjection() as Vector3;

  // Calculate distance from camera to focal point
  const distance = vec3.distance(position, focalPoint);

  // To flip vertically (top-bottom), we need to:
  // 1. Move camera to the opposite side (negate direction)
  // 2. Flip the view up vector
  const flippedDirection = vec3.negate(vec3.create(), directionOfProjection);
  const newPosition = vec3.create();
  vec3.scaleAndAdd(newPosition, focalPoint, flippedDirection, -distance);

  const flippedViewUp = vec3.negate(vec3.create(), viewUp) as Vector3;

  camera.setPosition(...(newPosition as Vector3));
  camera.setFocalPoint(...focalPoint);
  camera.setViewUp(...flippedViewUp);

  view.renderWindow.render();
}

/**
 * Applies a 90-degree clockwise rotation to a specific view
 */
export function applyRotateRight(view: VtkViewApi) {
  const camera = view.renderer.getActiveCamera();

  // Roll the camera -90 degrees (clockwise)
  camera.roll(-90);
  camera.orthogonalizeViewUp();

  view.renderWindow.render();
}

/**
 * Applies a 90-degree counter-clockwise rotation to a specific view
 */
export function applyRotateLeft(view: VtkViewApi) {
  const camera = view.renderer.getActiveCamera();

  // Roll the camera +90 degrees (counter-clockwise)
  camera.roll(90);
  camera.orthogonalizeViewUp();

  view.renderWindow.render();
}