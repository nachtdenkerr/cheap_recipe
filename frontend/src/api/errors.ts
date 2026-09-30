/** A failed request, with the HTTP status the API answered (0: no answer at all). */
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message)
  }
}
