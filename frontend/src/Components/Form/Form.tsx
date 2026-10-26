import classNames from 'classnames';
import React from 'react';
import styles from './Form.module.css';

export function FormRow({ children }: { children: React.ReactNode }) {
  return <div className={styles.row}>{children}</div>;
}

export function FormLabel({ htmlFor, children }: { htmlFor?: string; children: React.ReactNode }) {
  return (
    <label className={styles.label} htmlFor={htmlFor}>
      {children}
    </label>
  );
}

export function FormInputHelpText({ text, isWarning }: { text: string; isWarning?: boolean }) {
  return <div className={classNames(styles.helpText, isWarning && styles.warning)}>{text}</div>;
}

export interface SelectOption {
  key: string;
  value: string;
  isDisabled?: boolean;
  hint?: string;
}

interface SelectInputProps {
  id?: string;
  className?: string;
  value: string;
  values: SelectOption[];
  isDisabled?: boolean;
  onChange: (value: string) => void;
}

export function SelectInput({ id, className, value, values, isDisabled, onChange }: SelectInputProps) {
  const selected = values.find((option) => option.key === value);

  return (
    <>
      <select
        id={id}
        className={classNames(styles.input, styles.select, className)}
        value={value}
        disabled={isDisabled}
        onChange={(event) => onChange(event.target.value)}
      >
        {values.map((option) => (
          <option key={option.key} value={option.key} disabled={option.isDisabled}>
            {option.value}
          </option>
        ))}
      </select>
      {selected?.hint ? <div className={styles.helpText}>{selected.hint}</div> : null}
    </>
  );
}

interface TextInputProps extends Omit<React.InputHTMLAttributes<HTMLInputElement>, 'onChange'> {
  onChange: (value: string) => void;
}

export function TextInput({ className, onChange, ...otherProps }: TextInputProps) {
  return (
    <input
      type="text"
      className={classNames(styles.input, className)}
      onChange={(event) => onChange(event.target.value)}
      {...otherProps}
    />
  );
}

interface CheckInputProps {
  checked: boolean;
  isIndeterminate?: boolean;
  label?: string;
  onChange: (checked: boolean, shiftKey: boolean) => void;
}

export function CheckInput({ checked, isIndeterminate, label, onChange }: CheckInputProps) {
  return (
    <input
      type="checkbox"
      className={styles.check}
      checked={checked}
      aria-label={label}
      ref={(input) => {
        if (input) {
          input.indeterminate = !!isIndeterminate;
        }
      }}
      onChange={(event) =>
        onChange(event.target.checked, (event.nativeEvent as MouseEvent).shiftKey ?? false)
      }
    />
  );
}
