/** Route ids come from the URL: only a positive integer is worth asking the API about. */
export const isPositiveId = (id: number) => Number.isInteger(id) && id > 0;
