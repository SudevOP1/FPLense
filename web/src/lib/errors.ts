import { ApiError } from "@/api/client";

/** Short, human message for any error shown in the UI. */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.friendly;
  if (error instanceof Error) return error.message;
  return "Something went wrong.";
}
