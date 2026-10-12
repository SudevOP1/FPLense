import { useState } from "react";

/**
 * Hotlinked Premier League photo (never re-hosted), lazy-loaded, in a box that reserves its
 * aspect ratio; falls back to a neutral silhouette when the image fails. `face` keeps only the
 * top half of the photo (head and shoulders) for compact pitch cards.
 */
export function PlayerPhoto({
  src,
  name,
  face = false,
  className = "",
}: {
  src: string | null | undefined;
  name: string;
  face?: boolean;
  className?: string;
}) {
  const [failed, setFailed] = useState(false);
  return (
    <div className={`relative overflow-hidden ${face ? "aspect-[110/70]" : "aspect-[110/140]"} ${className}`}>
      {src && !failed ? (
        // PLAN.md asks for alt text like "Photo of Bukayo Saka"
        // eslint-disable-next-line jsx-a11y/img-redundant-alt
        <img
          src={src}
          alt={`Photo of ${name}`}
          loading="lazy"
          decoding="async"
          width={110}
          height={140}
          referrerPolicy="no-referrer"
          className="h-full w-full object-cover object-top"
          onError={() => setFailed(true)}
        />
      ) : (
        <svg
          role="img"
          aria-label={`Photo of ${name} (not available)`}
          data-testid="photo-fallback"
          viewBox={face ? "0 0 110 70" : "0 0 110 140"}
          className="h-full w-full text-muted"
        >
          <rect width="110" height="140" fill="currentColor" opacity="0.18" />
          <circle cx="55" cy="52" r="24" fill="currentColor" opacity="0.75" />
          <path d="M14 140c4-34 20-50 41-50s37 16 41 50z" fill="currentColor" opacity="0.75" />
        </svg>
      )}
    </div>
  );
}
