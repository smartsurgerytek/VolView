import vtkAbstractWidgetFactory from '@kitware/vtk.js/Widgets/Core/AbstractWidgetFactory';
import {
  IAnnotationToolWidgetInitialValues,
  vtkAnnotationToolWidget,
  vtkAnnotationWidgetPointState,
  vtkAnnotationWidgetState,
} from '@/src/vtk/ToolWidgetUtils/types';

export { InteractionState } from './behavior';

export interface vtkDentalWidgetPointState
  extends vtkAnnotationWidgetPointState {}

export interface vtkDentalWidgetState extends vtkAnnotationWidgetState {
  setIsPlaced(isPlaced: boolean): boolean;
  getIsPlaced(): boolean;
  getFirstPoint(): vtkDentalWidgetPointState;
  getSecondPoint(): vtkDentalWidgetPointState;
}

export interface vtkDentalViewWidget extends vtkAnnotationToolWidget {
  setInteractionState(state: InteractionState): boolean;
  getInteractionState(): InteractionState;
  getWidgetState(): vtkDentalWidgetState;
}

export interface IDentalWidgetInitialValues
  extends IAnnotationToolWidgetInitialValues {
  isPlaced: boolean;
}

export interface vtkDentalWidget
  extends vtkAbstractWidgetFactory<vtkDentalViewWidget> {
  getWidgetState(): vtkDentalWidgetState;
}

function newInstance(initialValues: IDentalWidgetInitialValues): vtkDentalWidget;

export declare const vtkDentalWidget: {
  newInstance: typeof newInstance;
};
export default vtkDentalWidget;
