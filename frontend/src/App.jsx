import { createBrowserRouter, RouterProvider } from 'react-router-dom';

import Layout from './components/Layout';
import NotFound from './routes/NotFound';
import PollDetail from './routes/PollDetail';
import Polls from './routes/Polls';

const router = createBrowserRouter([
  {
    element: <Layout />,
    children: [
      { path: '/', element: <Polls /> },
      { path: '/encuestas/:pollId', element: <PollDetail /> },
      { path: '*', element: <NotFound /> },
    ],
  },
]);

export default function App() {
  return <RouterProvider router={router} />;
}
