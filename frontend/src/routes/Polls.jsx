import { useMemo } from 'react';
import { useQuery } from '@apollo/client';
import {
  Alert,
  AlertDescription,
  AlertIcon,
  Badge,
  Box,
  Button,
  Grid,
  GridItem,
  HStack,
  Icon,
  Text,
  VStack,
} from '@chakra-ui/react';
import { FiBarChart2, FiRefreshCw } from 'react-icons/fi';

import { LIST_POLLS } from '../api/polls';
import { CreatePollForm } from '../components/CreatePollForm';
import { PageHeader } from '../components/PageHeader';
import { PollCard } from '../components/PollCard';
import { PollsContextBar } from '../components/PollsContextBar';
import { EmptyState, ErrorState, LoadingState } from '../components/Results';
import { usePollsContext } from '../context/PollsContext';

export default function Polls() {
  const { channelId, userId } = usePollsContext();
  const { data, loading, error, refetch } = useQuery(LIST_POLLS, {
    variables: { channelId },
    skip: !channelId,
  });

  const polls = useMemo(() => {
    const items = [...(data?.polls ?? [])];
    return items.sort(
      (a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime(),
    );
  }, [data]);

  return (
    <Box>
      <PageHeader
        title="Encuestas"
        description="Interfaz del microservicio Polls. Consulta, crea, vota y cierra encuestas a través del API Gateway GraphQL."
        action={
          <Button
            variant="outline"
            leftIcon={<FiRefreshCw />}
            onClick={() => refetch()}
            isLoading={loading}
            isDisabled={!channelId}
          >
            Actualizar
          </Button>
        }
      />

      <PollsContextBar />

      {!channelId ? (
        <Alert status="info" rounded="xl">
          <AlertIcon />
          <AlertDescription fontSize="sm">
            Configura el ID del canal para consultar sus encuestas.
          </AlertDescription>
        </Alert>
      ) : null}

      {channelId && loading && !data ? (
        <LoadingState label="Consultando encuestas del canal en el gateway…" />
      ) : null}

      {channelId && error ? (
        <ErrorState
          title="No se pudieron cargar las encuestas"
          error={error}
          onRetry={() => refetch()}
        />
      ) : null}

      {channelId && !error && data ? (
        <Grid
          templateColumns={{ base: '1fr', xl: '360px minmax(0, 1fr)' }}
          gap={6}
          alignItems="start"
        >
          <GridItem>
            <VStack align="stretch" spacing={4} position={{ xl: 'sticky' }} top="6rem">
              <CreatePollForm
                channelId={channelId}
                authorId={userId}
                onCreated={() => refetch()}
              />
              <Alert status="info" rounded="xl" py={3}>
                <AlertIcon />
                <AlertDescription fontSize="xs">
                  El gateway descubre las encuestas desde los anuncios del canal.
                  Si acabas de crear una, pulsa Actualizar.
                </AlertDescription>
              </Alert>
            </VStack>
          </GridItem>

          <GridItem>
            <VStack align="stretch" spacing={4}>
              <HStack px={1}>
                <Icon as={FiBarChart2} color="gray.400" />
                <Text fontSize="sm" fontWeight="semibold" color="gray.600">
                  Encuestas del canal
                </Text>
                <Badge variant="subtle" colorScheme="brand">
                  {polls.length}
                </Badge>
              </HStack>

              {polls.length === 0 ? (
                <EmptyState
                  title="No hay encuestas en este canal"
                  description="Crea la primera encuesta desde el formulario. El gateway la devolverá al actualizar."
                />
              ) : (
                <VStack align="stretch" spacing={4}>
                  {polls.map((poll) => (
                    <PollCard
                      key={poll.pollId}
                      poll={poll}
                      onChanged={() => refetch()}
                    />
                  ))}
                </VStack>
              )}
            </VStack>
          </GridItem>
        </Grid>
      ) : null}
    </Box>
  );
}
