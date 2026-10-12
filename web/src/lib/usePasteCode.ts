import { useEffect, useRef } from "react";
import { extract, looksLikeCode } from "./teamCode";

/**
 * Pasting a team code anywhere on the page (outside a text field) hands it to `onCode`, so
 * Compare and Builder can ask "Load this team into slot B?".
 */
export function usePasteCode(onCode: (code: string) => void): void {
  const handler = useRef(onCode);
  handler.current = onCode;
  useEffect(() => {
    const onPaste = (e: ClipboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target?.closest("input, textarea, [contenteditable='true']")) return;
      const text = e.clipboardData?.getData("text") ?? "";
      if (!looksLikeCode(text)) return;
      e.preventDefault();
      handler.current(extract(text));
    };
    document.addEventListener("paste", onPaste);
    return () => document.removeEventListener("paste", onPaste);
  }, []);
}
