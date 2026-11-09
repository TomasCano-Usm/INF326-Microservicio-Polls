import { useEffect, useState } from 'react';
import {
  Badge,
  Box,
  Button,
  FormControl,
  FormLabel,
  Grid,
  HStack,
  Input,
  Text,
  useToast,
} from '@chakra-ui/react';
import { FiCheck } from 'react-icons/fi';

import { DEMO_MODE } from '../config';
import { usePollsContext } from '../context/PollsContext';

export function PollsContextBar() {
  const toast = useToast();
  const { channelId, userId, setContext } = usePollsContext();
  const [channelDraft, setChannelDraft] = useState(channelId);
  const [userDraft, setUserDraft] = useState(userId);

  useEffect(() => setChannelDraft(channelId), [channelId]);
  useEffect(() => setUserDraft(userId), [userId]);

  const handleSubmit = (event) => {
    event.preventDefault();
    setContext({ channelId: channelDraft, userId: userDraft });
    toast({
      title: 'Contexto actualizado',
      description: 'Las encuestas se consultarán con estos identificadores.',
      status: 'success',
      duration: 2500,
      isClosable: true,
    });
  };

  return (
    <Box
      as="form"
      onSubmit={handleSubmit}
      bg="white"
      borderWidth="1px"
      borderColor="gray.200"
      rounded="xl"
      p={5}
      mb={6}
    >
      <HStack mb={4} spacing={2}>
        <Text fontWeight="semibold" fontSize="sm">
          Contexto de trabajo
        </Text>
        {DEMO_MODE ? <Badge colorScheme="purple">Demo local</Badge> : null}
      </HStack>

      <Grid
        templateColumns={{ base: '1fr', md: '1fr 1fr auto' }}
        gap={4}
        alignItems="end"
      >
        <FormControl>
          <FormLabel fontSize="sm">ID del canal</FormLabel>
          <Input
            value={channelDraft}
            onChange={(event) => setChannelDraft(event.target.value)}
            placeholder="UUID del canal"
            size="sm"
            fontFamily="mono"
          />
        </FormControl>

        <FormControl>
          <FormLabel fontSize="sm">ID del usuario</FormLabel>
          <Input
            value={userDraft}
            onChange={(event) => setUserDraft(event.target.value)}
            placeholder="UUID del usuario"
            size="sm"
            fontFamily="mono"
          />
        </FormControl>

        <Button type="submit" size="sm" leftIcon={<FiCheck />}>
          Aplicar
        </Button>
      </Grid>

      <Text fontSize="xs" color="gray.500" mt={3}>
        {DEMO_MODE
          ? 'En modo demo estos IDs solo afectan a los datos locales de demostración.'
          : 'Estos IDs son identificadores de dominio, no credenciales. Se envían al gateway junto con cada operación de encuestas.'}
      </Text>
    </Box>
  );
}
