import {
  Alert,
  AlertDescription,
  AlertIcon,
  AlertTitle,
  Box,
  Button,
  Center,
  HStack,
  Heading,
  Spinner,
  Text,
  VStack,
} from '@chakra-ui/react';
import { FiInbox, FiRefreshCw } from 'react-icons/fi';

import { errorMessage } from '../utils/format';

export function LoadingState({ label = 'Cargando…' }) {
  return (
    <Center py={16}>
      <VStack spacing={4}>
        <Spinner size="xl" color="brand.500" thickness="4px" />
        <Text color="gray.500">{label}</Text>
      </VStack>
    </Center>
  );
}

export function ErrorState({
  title = 'No se pudo cargar la información',
  error,
  onRetry,
}) {
  return (
    <Alert
      status="error"
      variant="subtle"
      flexDirection="column"
      alignItems="flex-start"
      borderRadius="xl"
      py={5}
      px={6}
      gap={2}
    >
      <HStack>
        <AlertIcon />
        <AlertTitle>{title}</AlertTitle>
      </HStack>
      <AlertDescription>
        <Text fontSize="sm">{errorMessage(error)}</Text>
        {onRetry ? (
          <Button
            mt={4}
            size="sm"
            variant="outline"
            colorScheme="red"
            leftIcon={<FiRefreshCw />}
            onClick={onRetry}
          >
            Reintentar
          </Button>
        ) : null}
      </AlertDescription>
    </Alert>
  );
}

export function EmptyState({ title, description, action }) {
  return (
    <Center
      borderWidth="1px"
      borderStyle="dashed"
      borderColor="gray.300"
      borderRadius="xl"
      bg="white"
      px={6}
      py={12}
      textAlign="center"
    >
      <VStack spacing={3} maxW="md">
        <Box color="gray.300">
          <FiInbox size={38} />
        </Box>
        <Heading size="md">{title}</Heading>
        {description ? (
          <Text color="gray.500" fontSize="sm">
            {description}
          </Text>
        ) : null}
        {action}
      </VStack>
    </Center>
  );
}
