import { useState } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "@/i18n";
import "@/styles/curation.css";

/** A line for the user to paste into a terminal of their own, with a copy button. */
export function PasteLine({ line }: { line: string }) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);
  return (
    <>
      <pre>{line}</pre>
      <button
        type="button"
        onClick={() =>
          navigator.clipboard
            .writeText(line)
            .then(() => setCopied(true))
            .catch(() => window.prompt("Copy:", line))
        }
      >
        {copied ? t("curation.modal.copied") : t("curation.modal.copy")}
      </button>
    </>
  );
}

/** The start line of a curation or migration run, in a dialog of its own, above the page wherever it is opened. */
export function StartLineModal({
  title,
  note,
  line,
  onClose,
}: {
  title: string;
  note: string;
  line: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  return createPortal(
    <div className="cur-modal" role="dialog" aria-modal="true">
      <button type="button" className="cur-backdrop" aria-label="close" onClick={onClose} />
      <div className="cur-box">
        <h3>{title}</h3>
        <p>{note}</p>
        <div className="cur-actions">
          <PasteLine line={line} />
          <button type="button" onClick={onClose}>
            {t("curation.modal.close")}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
