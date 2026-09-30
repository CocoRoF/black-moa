import { createRoot } from 'react-dom/client';
import { ShellWindow } from './Shell';
import './styles.css';
import './font';
import './bridge';
import './theme';

createRoot(document.getElementById('root')!).render(<ShellWindow />);
