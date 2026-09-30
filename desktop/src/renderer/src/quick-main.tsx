import { createRoot } from 'react-dom/client';
import { QuickWindow } from './Quick';
import './styles.css';
import './font';
import './bridge';
import './theme';

createRoot(document.getElementById('root')!).render(<QuickWindow />);
