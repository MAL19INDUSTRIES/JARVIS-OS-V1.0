import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium transition-[color,background-color,border-color,opacity,transform] duration-200 ease-out disabled:pointer-events-none disabled:opacity-45 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background active:translate-y-px",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground hover:bg-primary/86",
        secondary: "border border-border bg-secondary text-foreground hover:border-bright hover:bg-accent",
        ghost: "text-muted-foreground hover:bg-accent hover:text-foreground",
        danger: "border border-destructive/45 bg-destructive/10 text-destructive hover:bg-destructive/18",
      },
      size: {
        default: "h-10 px-4 py-2",
        sm: "h-8 rounded px-3 text-xs",
        icon: "size-10",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

export function Button({ className, variant, size, asChild = false, ...props }: ButtonProps) {
  const Comp = asChild ? Slot : "button";
  return <Comp className={cn(buttonVariants({ variant, size, className }))} {...props} />;
}
