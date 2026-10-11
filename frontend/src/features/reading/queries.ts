import { sourcesQuery } from "@/features/sources";
import { blindspotsQuery } from "@/features/stories";

export function myNewsQueries() {
  return { sources: sourcesQuery({ days: 90 }), blindspots: blindspotsQuery({ days: 7 }) };
}
