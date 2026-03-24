import type { AnchorHTMLAttributes, ReactNode } from 'react';

type CtaButtonProps = AnchorHTMLAttributes<HTMLAnchorElement> & {
  children?: ReactNode;
  icon: ReactNode;
  variant?: 'primary' | 'secondary';
};

const CtaButton = ({
  children,
  className = '',
  icon,
  variant = 'primary',
  ...props
}: CtaButtonProps) => {
  const variantClasses =
    variant === 'secondary'
      ? 'cta-button--secondary border border-white/10 bg-surface-container-highest/20 text-white'
      : 'pulse-gradient text-on-primary-fixed';
  const classes = `cta-button inline-flex items-center justify-center overflow-hidden rounded-full ${variantClasses} ${className}`.trim();

  return (
    <a className={classes} {...props}>
      <span className="cta-button__label">{children}</span>
      <span aria-hidden="true" className="cta-button__icon">
        {icon}
      </span>
    </a>
  );
};

export default CtaButton;
