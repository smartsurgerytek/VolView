
import { useDICOMStore } from '../store/datasets-dicom';

export async function generateRecord(selectedDicomIds: string[]) {  
    const { VITE_FOUNDATION_WEB } = import.meta.env;

    console.log("=========================Calling generateRecord=========================");

    console.log("DEBUG: Sending Record to Parent Origin:", VITE_FOUNDATION_WEB);
    console.log("DEBUG: Selected IDs:", selectedDicomIds);

    const dicomStore = useDICOMStore();  

    const selectedFiles = selectedDicomIds.map(id => {  
        return dicomStore.volumeInfo[id];  
    }); 

    const sopInstanceUidList = selectedFiles.map(file => file.SOPInstanceUID);

    if (!VITE_FOUNDATION_WEB) {
        console.error("ERROR: VITE_FOUNDATION_WEB is undefined! Record message will not be sent.");
        return;
    }

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