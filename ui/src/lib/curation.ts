import { useMutation } from "@tanstack/react-query";
import { startCurationMutation } from "@/client/@tanstack/react-query.gen";
import { usePersona } from "@/lib/persona";

/** The line that starts memory-curation's report as the chosen persona, for the user to paste into a terminal. */
export function useStartCuration(): {
  start: () => void;
  pending: boolean;
  error: string | null;
  can: boolean;
  line: string | null;
  waiting: boolean;
  clear: () => void;
} {
  const { persona } = usePersona();
  const mutation = useMutation(startCurationMutation());
  const detail = (mutation.error as { detail?: unknown } | null)?.detail;
  return {
    start: () => {
      if (persona) mutation.mutate({ body: { identity: persona } });
    },
    pending: mutation.isPending,
    error: mutation.error ? (typeof detail === "string" ? detail : JSON.stringify(mutation.error)) : null,
    can: persona !== null,
    line: mutation.data?.command ?? null,
    waiting: mutation.data?.waiting ?? false,
    clear: () => mutation.reset(),
  };
}
