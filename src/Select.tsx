import type { ComponentPropsWithoutRef } from 'react';
import { ChevronDown } from 'lucide-react';

export default function Select(props: ComponentPropsWithoutRef<'select'>) {
  return <span className="select-field">
    <select {...props} />
    <ChevronDown size={14} aria-hidden="true" />
  </span>;
}
