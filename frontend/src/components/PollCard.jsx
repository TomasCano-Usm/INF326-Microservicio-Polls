import { useRef, useState } from 'react';
import { useMutation } from '@apollo/client';
import {
  Alert,
  AlertDialog,
  AlertDialogBody,
  AlertDialogContent,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogOverlay,
  AlertIcon,
  Badge,
  Box,
  Button,
  Divider,
  Flex,
  HStack,
  Link,
  Progress,
  Text,
  VStack,
  useDisclosure,
  useToast,
} from '@chakra-ui/react';
import { FiExternalLink, FiLock, FiUser } from 'react-icons/fi';
import { Link as RouterLink } from 'react-router-dom';

import { CLOSE_POLL, VOTE } from '../api/polls';
import { usePollsContext } from '../context/PollsContext';
import {
  errorMessage,
  formatDateTime,
  pollStatusMeta,
  shortId,
} from '../utils/format';

export function PollCard({ poll, onChanged }) {
  const toast = useToast();
  const { userId } = usePollsContext();
  const [votingOptionId, setVotingOptionId] = useState(null);
  const [vote] = useMutation(VOTE);
  const [closePoll, { loading: closing }] = useMutation(CLOSE_POLL);
  const closeDialog = useDisclosure();
  const cancelRef = useRef();

  const status = pollStatusMeta(poll.status);
  const isOpen = poll.status === 'open';
  const isAuthor = Boolean(userId && userId === poll.authorId);
  const totalVotes = poll.totalVotes ?? 0;
  const options = Array.isArray(poll.options) ? poll.options : [];

  const handleVote = async (optionId) => {
    if (!userId) {
      toast({
        title: 'Selecciona un usuario',
        description: 'Necesitas un usuario para votar.',
        status: 'warning',
        duration: 3000,
        isClosable: true,
      });
      return;
    }
    setVotingOptionId(optionId);
    try {
      await vote({
        variables: {
          pollId: poll.pollId,
          voterId: userId,
          optionId,
        },
      });
      toast({
        title: 'Voto registrado',
        status: 'success',
        duration: 2500,
        isClosable: true,
      });
      onChanged?.();
    } catch (error) {
      toast({
        title: 'No se pudo votar',
        description: errorMessage(error),
        status: 'error',
        duration: 5000,
        isClosable: true,
      });
    } finally {
      setVotingOptionId(null);
    }
  };

  const handleClose = async () => {
    if (!userId) return;
    try {
      await closePoll({
        variables: {
          pollId: poll.pollId,
          authorId: userId,
        },
      });
      closeDialog.onClose();
      toast({
        title: 'Encuesta cerrada',
        status: 'success',
        duration: 2500,
        isClosable: true,
      });
      onChanged?.();
    } catch (error) {
      toast({
        title: 'No se pudo cerrar la encuesta',
        description: errorMessage(error),
        status: 'error',
        duration: 5000,
        isClosable: true,
      });
    }
  };

  return (
    <Box
      id={`poll-${poll.pollId}`}
      bg="white"
      borderWidth="1px"
      borderColor="gray.200"
      rounded="xl"
      p={5}
      scrollMarginTop="6rem"
    >
      <Flex align="flex-start" gap={3} mb={4}>
        <Box flex="1" minW={0}>
          <HStack spacing={2} mb={2} flexWrap="wrap">
            <Badge colorScheme={status.colorScheme}>{status.label}</Badge>
            <Badge variant="outline" colorScheme="gray">
              {totalVotes} voto{totalVotes === 1 ? '' : 's'}
            </Badge>
            {isAuthor ? <Badge colorScheme="purple">Tu encuesta</Badge> : null}
          </HStack>
          <Text fontWeight="semibold" fontSize="md" lineHeight="1.35">
            {poll.question}
          </Text>
        </Box>
        <Link
          as={RouterLink}
          to={`/encuestas/${poll.pollId}`}
          color="gray.400"
          aria-label="Ver detalle de la encuesta"
          _hover={{ color: 'brand.500' }}
        >
          <FiExternalLink />
        </Link>
      </Flex>

      {poll.creationError ? (
        <Alert status="error" rounded="lg" mb={4} py={2}>
          <AlertIcon />
          <Text fontSize="xs">{poll.creationError}</Text>
        </Alert>
      ) : null}

      <VStack align="stretch" spacing={3}>
        {options.map((option) => {
          const percentage =
            totalVotes > 0 ? Math.round((option.voteCount / totalVotes) * 100) : 0;
          const isVoting = votingOptionId === option.optionId;
          return (
            <Box key={option.optionId}>
              <Flex align="center" gap={3} mb={1}>
                <Text flex="1" fontSize="sm" fontWeight="medium">
                  {option.text}
                </Text>
                <Text fontSize="xs" color="gray.500" whiteSpace="nowrap">
                  {option.voteCount} · {percentage}%
                </Text>
                {isOpen ? (
                  <Button
                    size="xs"
                    variant="outline"
                    onClick={() => handleVote(option.optionId)}
                    isLoading={isVoting}
                    isDisabled={!userId || Boolean(votingOptionId)}
                  >
                    Votar
                  </Button>
                ) : null}
              </Flex>
              <Progress
                value={percentage}
                size="xs"
                rounded="full"
                colorScheme={isOpen ? 'brand' : 'gray'}
                bg="gray.100"
              />
            </Box>
          );
        })}
      </VStack>

      <Divider my={4} />

      <Flex align="center" gap={2} flexWrap="wrap">
        <HStack spacing={1} fontSize="xs" color="gray.500">
          <FiUser />
          <Text>
            Autor: {isAuthor ? 'tú' : shortId(poll.authorId, 12)}
          </Text>
        </HStack>
        <Text fontSize="xs" color="gray.300">
          ·
        </Text>
        <Text fontSize="xs" color="gray.500">
          Cierra: {formatDateTime(poll.closesAt)}
        </Text>
        {isOpen && isAuthor ? (
          <Button
            ml="auto"
            size="xs"
            variant="outline"
            colorScheme="red"
            leftIcon={<FiLock />}
            onClick={closeDialog.onOpen}
            isDisabled={closing}
          >
            Cerrar encuesta
          </Button>
        ) : null}
        {isOpen && !userId ? (
          <Text ml="auto" fontSize="xs" color="orange.600">
            Selecciona un usuario para votar
          </Text>
        ) : null}
      </Flex>

      <AlertDialog
        isOpen={closeDialog.isOpen}
        leastDestructiveRef={cancelRef}
        onClose={closeDialog.onClose}
        isCentered
      >
        <AlertDialogOverlay>
          <AlertDialogContent>
            <AlertDialogHeader fontSize="lg" fontWeight="bold">
              Cerrar encuesta
            </AlertDialogHeader>
            <AlertDialogBody>
              ¿Cerrar la encuesta “{poll.question}”? No se podrán registrar
              nuevos votos.
            </AlertDialogBody>
            <AlertDialogFooter>
              <Button ref={cancelRef} onClick={closeDialog.onClose}>
                Cancelar
              </Button>
              <Button
                colorScheme="red"
                ml={3}
                isLoading={closing}
                onClick={handleClose}
              >
                Cerrar definitivamente
              </Button>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialogOverlay>
      </AlertDialog>
    </Box>
  );
}
