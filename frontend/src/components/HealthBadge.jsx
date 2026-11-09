import { useQuery } from '@apollo/client';
import { Badge, Tooltip } from '@chakra-ui/react';

import { HEALTH } from '../api/health';
import { DEMO_MODE } from '../config';

export function HealthBadge() {
  const { data, loading, error } = useQuery(HEALTH, {
    skip: DEMO_MODE,
    pollInterval: 30000,
    fetchPolicy: 'cache-and-network',
  });

  if (DEMO_MODE) {
    return (
      <Tooltip label="Datos locales de demostración. No se consulta el gateway.">
        <Badge
          colorScheme="purple"
          variant="subtle"
          px={2}
          py={1}
          borderRadius="md"
        >
          Modo demo
        </Badge>
      </Tooltip>
    );
  }

  if (loading && !data) {
    return (
      <Badge colorScheme="gray" variant="subtle" px={2} py={1} borderRadius="md">
        Verificando gateway…
      </Badge>
    );
  }

  if (error || !data?.health) {
    return (
      <Tooltip label="No se pudo consultar el API Gateway GraphQL.">
        <Badge colorScheme="red" variant="subtle" px={2} py={1} borderRadius="md">
          Gateway desconectado
        </Badge>
      </Tooltip>
    );
  }

  return (
    <Tooltip label="Consultado vía GraphQL al API Gateway.">
      <Badge colorScheme="green" variant="subtle" px={2} py={1} borderRadius="md">
        Gateway OK · v{data.health.version}
      </Badge>
    </Tooltip>
  );
}
