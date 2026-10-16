import { useEffect, useState } from "react";

import { publicUrl } from "@/shared/lib/publicUrl";

type Copy = "idle" | "copied" | "failed";

/**
 * Share a story: the device's own share sheet where there is one (phones), otherwise a copied
 * link and the messengers most used in the region. The link is the story page itself; link
 * previews of it carry the headline and the outlet count (backend api/routers/share.py).
 */
export function ShareStory({ id, title }: { id: number; title: string }) {
  const url = publicUrl(`/stories/${id}`);
  const [copy, setCopy] = useState<Copy>("idle");
  const canShare = typeof navigator.share === "function";
  const message = encodeURIComponent(`${title} ${url}`);

  useEffect(() => {
    if (copy === "idle") return;
    const timer = window.setTimeout(() => setCopy("idle"), 4000);
    return () => window.clearTimeout(timer);
  }, [copy]);

  async function copyLink() {
    try {
      await navigator.clipboard.writeText(url);
      setCopy("copied");
    } catch {
      setCopy("failed");
    }
  }

  async function share() {
    try {
      await navigator.share({ title, url });
    } catch (error) {
      // Closing the share sheet is not an error; anything else falls back to the copied link.
      if ((error as DOMException).name !== "AbortError") await copyLink();
    }
  }

  const external = { target: "_blank", rel: "noopener noreferrer", className: "btn btn--sm btn--ghost" };
  return (
    <div className="share" role="group" aria-label="Share this story">
      {canShare && (
        <button type="button" className="btn btn--sm" onClick={share}>Share</button>
      )}
      <button type="button" className="btn btn--sm" onClick={copyLink}>Copy link</button>
      {!canShare && (
        <>
          <a {...external} href={`https://wa.me/?text=${message}`}>WhatsApp</a>
          <a {...external} href={`viber://forward?text=${message}`}>Viber</a>
          <a {...external} href={`https://www.facebook.com/sharer/sharer.php?u=${encodeURIComponent(url)}`}>Facebook</a>
        </>
      )}
      <span className="meta" role="status">
        {copy === "copied" ? "Link copied" : copy === "failed" ? "Could not copy; use the address bar" : ""}
      </span>
    </div>
  );
}
