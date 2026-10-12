import { Link } from "react-router-dom";
import { useTitle } from "@/lib/useTitle";

export default function NotFound() {
  useTitle("Not found");
  return (
    <div className="mx-auto flex max-w-md flex-col items-center gap-3 py-16 text-center">
      <p className="num text-6xl font-bold text-coral">404</p>
      <h1 className="text-2xl font-bold">Offside!</h1>
      <p className="text-muted">That page isn't on the team sheet. It may have moved, or the link was cut short.</p>
      <Link to="/" className="btn-primary">
        Back to Home
      </Link>
    </div>
  );
}
