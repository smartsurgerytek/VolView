import { useDICOMStore } from '../store/datasets-dicom';

export async function generateRecord(selectedDicomIds: string[]) {  
    const { VITE_FOUNDATION_WEB } = import.meta.env;

    const dicomStore = useDICOMStore();  
    
    const selectedFiles = selectedDicomIds.map(id => {  
        return dicomStore.volumeInfo[id];  
    }); 

    const sopInstanceUidList = selectedFiles.map(file => file.SOPInstanceUID);

    // Send DICOM SOP Instance UIDs to the parent window
    // IMPORTANT: Replace 'http://localhost:8080' with the actual origin of your Blazor parent application.
    // This is crucial for security.
    window.parent.postMessage(
        {
            type: 'DICOM_SOP_INSTANCE_UIDS',
            payload: sopInstanceUidList,
        },
        VITE_FOUNDATION_WEB
    );
}