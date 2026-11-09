import React from 'react';
import ReactDOM from 'react-dom/client';
import {
  ApolloClient,
  ApolloProvider,
  HttpLink,
  InMemoryCache,
} from '@apollo/client';
import { ChakraProvider, ColorModeScript } from '@chakra-ui/react';

import App from './App';
import { demoLink } from './api/demoLink';
import { DEMO_MODE, GATEWAY_URI } from './config';
import { PollsProvider } from './context/PollsContext';
import theme from './theme';

const client = new ApolloClient({
  link: DEMO_MODE ? demoLink : new HttpLink({ uri: GATEWAY_URI }),
  cache: new InMemoryCache(),
  defaultOptions: {
    watchQuery: {
      fetchPolicy: 'cache-and-network',
    },
    query: {
      fetchPolicy: 'network-only',
    },
  },
});

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <ApolloProvider client={client}>
      <ChakraProvider theme={theme}>
        <ColorModeScript initialColorMode={theme.config.initialColorMode} />
        <PollsProvider>
          <App />
        </PollsProvider>
      </ChakraProvider>
    </ApolloProvider>
  </React.StrictMode>,
);
