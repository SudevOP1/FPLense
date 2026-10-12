import { AnimatePresence, motion } from "framer-motion";
import { useId, useRef, useState } from "react";
import { COPIED_MS, DURATION } from "@/lib/motion";
import { decode, shareUrl, TeamCodeError } from "@/lib/teamCode";
import { useToast } from "@/lib/toast";

async function copyText(text: string, fallbackInput: HTMLInputElement | null): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // Clipboard API unavailable (http, old browser): select the text so the user can copy it
    fallbackInput?.focus();
    fallbackInput?.select();
    return false;
  }
}

/** Team code with one-click copy (Clipboard API, select-all fallback) and a share-link copy. */
export function CodeBox({ code, route = "/compare", compact = false }: { code: string; route?: string; compact?: boolean }) {
  const toast = useToast();
  const input = useRef<HTMLInputElement>(null);
  const [copied, setCopied] = useState<"code" | "link" | null>(null);
  const id = useId();

  const copy = async (what: "code" | "link") => {
    const ok = await copyText(what === "code" ? code : shareUrl(route, code), input.current);
    if (ok) {
      setCopied(what);
      toast.show(what === "code" ? "Team code copied" : "Share link copied", { tone: "good" });
      window.setTimeout(() => setCopied(null), COPIED_MS);
    } else {
      toast.show("Press Ctrl+C to copy the selected code");
    }
  };

  const tick = (what: "code" | "link", label: string) => (
    <AnimatePresence mode="wait" initial={false}>
      <motion.span
        key={copied === what ? "done" : "idle"}
        initial={{ opacity: 0, scale: 0.8 }}
        animate={{ opacity: 1, scale: 1 }}
        exit={{ opacity: 0, scale: 0.8 }}
        transition={{ duration: DURATION.fast }}
      >
        {copied === what ? "✓ Copied" : label}
      </motion.span>
    </AnimatePresence>
  );

  return (
    <div className={`flex flex-col gap-1.5 ${compact ? "" : "card p-3"}`}>
      <label htmlFor={id} className="label">
        Team code
      </label>
      <div className="flex flex-wrap gap-2">
        <input
          ref={input}
          id={id}
          readOnly
          value={code}
          onFocus={(e) => e.currentTarget.select()}
          className="field num min-w-0 flex-1 truncate text-xs"
        />
        <button type="button" className="btn-primary" onClick={() => copy("code")}>
          {tick("code", "Copy code")}
        </button>
        <button type="button" className="btn-secondary" onClick={() => copy("link")}>
          {tick("link", "Share link")}
        </button>
      </div>
    </div>
  );
}

/**
 * Paste field for a code or a share URL. The format and checksum are checked instantly in the
 * browser (lib/teamCode.ts); `onLoad` runs the server decode for the squad itself.
 */
export function PasteCodeField({
  onLoad,
  busy = false,
  serverError,
  label = "Paste a team code",
  button = "Load team",
}: {
  onLoad: (code: string) => void;
  busy?: boolean;
  serverError?: string | null;
  label?: string;
  button?: string;
}) {
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const id = useId();
  const errId = useId();
  const submit = () => {
    try {
      decode(text);
      setError(null);
      onLoad(text.trim());
    } catch (e) {
      setError(e instanceof TeamCodeError ? e.message : "That code couldn't be read.");
    }
  };
  const shown = error ?? serverError ?? null;
  return (
    <form
      className="flex flex-col gap-1.5"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <label htmlFor={id} className="label">
        {label}
      </label>
      <div className="flex gap-2">
        <input
          id={id}
          value={text}
          placeholder="FPLN-2627-… or a share link"
          aria-invalid={shown ? true : undefined}
          aria-describedby={shown ? errId : undefined}
          onChange={(e) => {
            setText(e.target.value);
            setError(null);
          }}
          className="field num min-w-0 flex-1 text-xs"
        />
        <button type="submit" className="btn-secondary" disabled={!text.trim() || busy}>
          {button}
        </button>
      </div>
      {shown && (
        <p id={errId} role="alert" className="text-sm text-bad">
          {shown}
        </p>
      )}
    </form>
  );
}

