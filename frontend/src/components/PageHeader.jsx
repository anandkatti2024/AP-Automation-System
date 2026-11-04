import { useState } from "react";
import { Mail, RefreshCw, Upload } from "lucide-react";

function PageHeader({
  onRefresh,
  onUpload,
  onImportEmail,
  uploading,
  canUpload,
}) {
  const [draggingFiles, setDraggingFiles] = useState(false);

  function handleDrop(event) {
    event.preventDefault();
    setDraggingFiles(false);
    if (!uploading && canUpload) {
      onUpload(Array.from(event.dataTransfer.files));
    }
  }

  return (
    <div className="page-heading">
      <div>
        <div className="eyebrow">ACCOUNTS PAYABLE</div>
        <h1>Invoice dashboard</h1>
        <p>Monitor invoices, payable amounts and processing status.</p>
      </div>
      <div className="heading-actions">
        <button className="button secondary" onClick={onRefresh}>
          <RefreshCw size={16} /> Refresh
        </button>
        {canUpload && (
          <>
            <label
              className={`button primary upload-drop-target ${uploading ? "disabled" : ""} ${draggingFiles ? "is-dragging" : ""}`}
              onDragEnter={(event) => {
                event.preventDefault();
                setDraggingFiles(true);
              }}
              onDragOver={(event) => event.preventDefault()}
              onDragLeave={(event) => {
                if (!event.currentTarget.contains(event.relatedTarget)) {
                  setDraggingFiles(false);
                }
              }}
              onDrop={handleDrop}
            >
              <Upload size={17} />
              {uploading ? "Uploading..." : "Upload or drop invoices"}
              <input
                type="file"
                accept=".pdf,.jpg,.jpeg,.png,.tif,.tiff"
                multiple
                hidden
                disabled={uploading}
                onChange={(event) => {
                  onUpload(Array.from(event.target.files || []));
                  event.target.value = "";
                }}
              />
            </label>
            <label className={`button secondary ${uploading ? "disabled" : ""}`}>
              <Mail size={16} /> Import .eml
              <input
                type="file"
                accept=".eml,message/rfc822"
                hidden
                disabled={uploading}
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  if (file) onImportEmail(file);
                  event.target.value = "";
                }}
              />
            </label>
          </>
        )}
      </div>
    </div>
  );
}

export default PageHeader;
