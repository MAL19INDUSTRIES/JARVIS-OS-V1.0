import { cn } from "@/lib/utils";
import type { JarvisMode, JarvisState } from "@/hooks/use-jarvis-socket";

export function Reactor({ state, mode = "jarvis" }: { state: JarvisState; mode?: JarvisMode }) {
  return (
    <div className={cn("reactor", `reactor-${state.toLowerCase()}`)} aria-label={`${mode.toUpperCase()} state: ${state}`} role="img">
      <div className="reactor-orbit orbit-a" />
      <div className="reactor-orbit orbit-b" />
      <div className="reactor-spokes" />
      <div className="reactor-core"><span>{mode[0].toUpperCase()}</span></div>
    </div>
  );
}
