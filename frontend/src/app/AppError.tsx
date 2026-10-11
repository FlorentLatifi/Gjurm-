import { useRouteError } from "react-router-dom";

/**
 * Last line of defence: an error outside any page (the shell itself). Pages have their own
 * boundary inside the shell (RouteError), so this should never be seen.
 */
export function AppError() {
  const error = useRouteError();
  console.error("Application error", error);
  return (
    <main id="main" className="state state--error" role="alert">
      <h1 className="state__title">GJURMË could not start</h1>
      <p>Reloading usually helps. If it keeps happening, please tell us.</p>
      <button type="button" className="btn btn--sm" onClick={() => window.location.reload()}>
        Reload page
      </button>
    </main>
  );
}
