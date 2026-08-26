// Voice mode toggle component
import Toggle from '@cloudscape-design/components/toggle';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Box from '@cloudscape-design/components/box';

interface VoiceModeToggleProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
}

export default function VoiceModeToggle({ checked, onChange, disabled }: VoiceModeToggleProps) {
  return (
    <SpaceBetween size="xs" direction="horizontal">
      <Box variant="awsui-key-label">Mode:</Box>
      <Toggle
        checked={checked}
        onChange={({ detail }) => onChange(detail.checked)}
        disabled={disabled}
        ariaLabel="Voice mode toggle"
      >
        {checked ? 'Voice' : 'Text'}
      </Toggle>
    </SpaceBetween>
  );
}
