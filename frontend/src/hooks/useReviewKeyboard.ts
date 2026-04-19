import { useEffect } from "react";

interface Options {
  total: number;
  focusedIdx: number;
  setFocusedIdx: (fn: (i: number) => number) => void;
  onApprove: () => void;
  onReject: () => void;
  enabled: boolean;
}

/**
 * Keyboard shortcuts for the milestone review queue.
 *
 * j / ArrowDown  — next card
 * k / ArrowUp    — previous card
 * a              — approve focused card
 * r              — reject focused card
 *
 * Disabled when focus is inside an input/textarea (e.g. label editing).
 */
export function useReviewKeyboard({
  total,
  focusedIdx,
  setFocusedIdx,
  onApprove,
  onReject,
  enabled,
}: Options) {
  useEffect(() => {
    if (!enabled) return;

    const handler = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;

      switch (e.key) {
        case "j":
        case "ArrowDown":
          e.preventDefault();
          setFocusedIdx((i) => Math.min(i + 1, total - 1));
          break;
        case "k":
        case "ArrowUp":
          e.preventDefault();
          setFocusedIdx((i) => Math.max(i - 1, 0));
          break;
        case "a":
          e.preventDefault();
          onApprove();
          break;
        case "r":
          e.preventDefault();
          onReject();
          break;
      }
    };

    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [enabled, total, focusedIdx, onApprove, onReject, setFocusedIdx]);
}
