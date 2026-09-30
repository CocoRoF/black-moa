import { createRoot } from 'react-dom/client';
import { AvatarWindow } from './Avatar';
import './styles.css';
import './font';
import './bridge';
import './theme';

createRoot(document.getElementById('root')!).render(<AvatarWindow />);
