import { createRoot } from 'react-dom/client';
import { ChipWindow } from './Chip';
import './styles.css';
import './font';
import './bridge';

createRoot(document.getElementById('root')!).render(<ChipWindow />);
