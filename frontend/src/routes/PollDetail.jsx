import { useQuery } from '@apollo/client';
import {
  Badge,
  Box,
  Button,
  Flex,
  HStack,
  Heading,
  Icon,
  Link,
  Spacer,
  Text,
} from '@chakra-ui/react';
import { FiArrowLeft, FiBarChart2, FiRefreshCw } from 'react-icons/fi';
import { Link as RouterLink, useParams } from 'react-router-dom';

import { GET_POLL } from '../api/polls';
import { PollCard } from '../components/PollCard';
import { PollsContextBar } from '../components/PollsContextBar';
import { EmptyState, ErrorState, LoadingState } from '../components/Results';
import { shortId } from '../utils/format';

export default function PollDetail() {
  const { pollId } = useParams();
  const { data, loading, error, refetch } = useQuery(GET_POLL, {
    variables: { id: pollId },
  });

  if (loading && !data) {
    return <LoadingState label="Consultando la encuesta en el gateway…" />;
  }

  if (error) {
    return (
      <ErrorState
        title="No se pudo cargar la encuesta"
        error={error}
        onRetry={() => refetch()}
      />
    );
  }

  if (!data?.poll) {
    return (
      <EmptyState
        title="Encuesta no encontrada"
        description="La encuesta no existe, no ha sido anunciada o ya no está disponible."
        action={
          <Button as={RouterLink} to="/" leftIcon={<FiArrowLeft />}>
            Volver a encuestas
          </Button>
        }
      />
    );
  }

  const poll = data.poll;

  return (
    <Box maxW="4xl">
      <Link
        as={RouterLink}
        to="/"
        display="inline-flex"
        alignItems="center"
        gap={1}
        mb={4}
        fontSize="sm"
        color="gray.500"
        _hover={{ color: 'brand.600', textDecoration: 'none' }}
      >
        <FiArrowLeft /> Volver a encuestas
      </Link>

      <Flex
        align={{ base: 'flex-start', md: 'center' }}
        direction={{ base: 'column', md: 'row' }}
        gap={3}
        mb={6}
      >
        <HStack spacing={3}>
          <Flex
            w={11}
            h={11}
            align="center"
            justify="center"
            rounded="xl"
            bg="brand.50"
            color="brand.600"
          >
            <Icon as={FiBarChart2} boxSize={5} />
          </Flex>
          <Box>
            <Heading size="lg" letterSpacing="-0.02em">
              Detalle de encuesta
            </Heading>
            <HStack mt={1} spacing={2} flexWrap="wrap">
              <Badge variant="subtle" colorScheme="gray">
                {shortId(poll.pollId, 12)}
              </Badge>
              <Text fontSize="xs" color="gray.500">
                Consultada con <code>poll(id:)</code>
              </Text>
            </HStack>
          </Box>
        </HStack>
        <Spacer />
        <Button
          size="sm"
          variant="outline"
          leftIcon={<FiRefreshCw />}
          onClick={() => refetch()}
          isLoading={loading}
        >
          Actualizar
        </Button>
      </Flex>

      <PollsContextBar />

      <PollCard poll={poll} onChanged={() => refetch()} />
    </Box>
  );
}
