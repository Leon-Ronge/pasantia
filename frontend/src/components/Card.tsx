import type { ReactNode } from "react";

interface CardProps {
  children: ReactNode;
  className?: string;
}

/** Superficie del sistema (fondo, borde y sombra de los tokens). */
export default function Card({ children, className = "" }: CardProps) {
  return <div className={`card ${className}`}>{children}</div>;
}
