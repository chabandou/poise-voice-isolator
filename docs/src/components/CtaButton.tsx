import type { AnchorHTMLAttributes, ReactNode } from 'react';

type CtaButtonProps = AnchorHTMLAttributes<HTMLAnchorElement> & {
  children?: ReactNode;
  icon?: ReactNode;
  variant?: 'primary' | 'ghost';
};

// Link styled like the app's QPushButton#primary / #ghost.
const CtaButton = ({
  children,
  className = '',
  icon,
  variant = 'primary',
  ...props
}: CtaButtonProps) => (
  <a className={`btn ${variant === 'ghost' ? 'btn-ghost' : 'btn-primary'} ${className}`.trim()} {...props}>
    {icon && (
      <span aria-hidden="true" className={`inline-flex ${variant === 'ghost' ? 'text-secondary' : ''}`}>
        {icon}
      </span>
    )}
    {children}
  </a>
);

export default CtaButton;
