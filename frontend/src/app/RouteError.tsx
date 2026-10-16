import { Component, type ErrorInfo, type ReactNode } from "react";

import { isChunkLoadError, reloadOnce } from "./chunkReload";
import { t } from "@/shared/i18n";

interface Props {
  children: ReactNode;
}

interface State {
  error: unknown;
  reloading: boolean;
}

/**
 * Keeps one page's failure inside the page: the header, navigation and footer stay usable.
 * A page whose code failed to load (typically an open tab after a deploy) triggers one reload;
 * anything else, or a second chunk failure, shows an error with a way out. The Layout keys this
 * boundary by path, so navigating elsewhere clears the error.
 */
export class RouteError extends Component<Props, State> {
  state: State = { error: null, reloading: false };

  static getDerivedStateFromError(error: unknown): Partial<State> {
    return { error };
  }

  componentDidCatch(error: unknown, info: ErrorInfo) {
    if (isChunkLoadError(error) && reloadOnce()) {
      this.setState({ reloading: true });
      return;
    }
    console.error("Page failed to render", error, info.componentStack);
  }

  render() {
    const { error, reloading } = this.state;
    if (!error) return this.props.children;
    if (reloading) {
      return (
        <div className="state" role="status">
          <p>{t("Loading the latest version of GJURMË…")}</p>
        </div>
      );
    }
    const chunk = isChunkLoadError(error);
    return (
      <div className="state state--error" role="alert">
        <h1 className="state__title">{chunk ? t("This page could not be loaded") : t("Something went wrong on this page")}</h1>
        <p>
          {chunk
            ? t("Check your connection, then reload. If the site was just updated, a reload fetches the new version.")
            : t("The rest of the site still works. Reloading usually helps; if it keeps happening, please tell us.")}
        </p>
        <button type="button" className="btn btn--sm" onClick={() => window.location.reload()}>
          {t("Reload page")}
        </button>
      </div>
    );
  }
}
