import { useState } from "react";
import { Sheet } from "@/components/ui/Sheet";
import { load, save } from "@/lib/storage";

const STEPS = [
  {
    title: "The best team, every week",
    body: "FPLense forecasts every player's points and picks the best legal £100m squad. Tap any card to see why the model likes a player.",
  },
  {
    title: "Load your own team",
    body: "Enter your FPL team ID on My Team to see expected points, a suggested lineup and the best transfers for your squad.",
  },
  {
    title: "Compare and share",
    body: "Add any team to the compare tray, line up to 3 side by side, and share teams as copy-paste codes or links.",
  },
];

/** First-visit 3-step tour; dismissable and remembered locally. */
export function Tour() {
  const [open, setOpen] = useState(() => !load("tourDone", false) && !navigator.webdriver);
  const [step, setStep] = useState(0);
  const close = () => {
    save("tourDone", true);
    setOpen(false);
  };
  const s = STEPS[step];
  return (
    <Sheet open={open} onClose={close} title={`Welcome to FPLense (${step + 1}/${STEPS.length})`} side="center">
      <div className="flex flex-col gap-4">
        <div>
          <h3 className="text-lg font-semibold">{s.title}</h3>
          <p className="mt-1 text-sm text-muted">{s.body}</p>
        </div>
        <div className="flex items-center justify-between gap-2">
          <button type="button" className="btn-ghost" onClick={close}>
            Skip
          </button>
          <div className="flex gap-2">
            {step > 0 && (
              <button type="button" className="btn-secondary" onClick={() => setStep(step - 1)}>
                Back
              </button>
            )}
            <button
              type="button"
              className="btn-primary"
              onClick={() => (step === STEPS.length - 1 ? close() : setStep(step + 1))}
            >
              {step === STEPS.length - 1 ? "Let's go" : "Next"}
            </button>
          </div>
        </div>
      </div>
    </Sheet>
  );
}
