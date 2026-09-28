import type { ReactNode } from 'react';
export default function ProfileSlides({ children }: { children: ReactNode }) {
  return <section className="character-hero" aria-label="角色立绘与档案">{children}</section>;
}
