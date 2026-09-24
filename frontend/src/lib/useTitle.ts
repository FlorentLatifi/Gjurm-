import { useEffect } from "react";

export function useTitle(title: string, description?: string) {
  useEffect(() => {
    document.title = title ? `${title} · GJURMË` : "GJURMË — Albanian & Balkan News Intelligence";
    if (description) {
      document.querySelector('meta[name="description"]')?.setAttribute("content", description);
    }
  }, [title, description]);
}
