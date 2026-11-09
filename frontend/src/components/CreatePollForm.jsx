import { useRef, useState } from 'react';
import { useMutation } from '@apollo/client';
import {
  Alert,
  AlertDescription,
  AlertIcon,
  Box,
  Button,
  Checkbox,
  FormControl,
  FormHelperText,
  FormLabel,
  HStack,
  IconButton,
  Input,
  Text,
  VStack,
  useToast,
} from '@chakra-ui/react';
import { FiBarChart2, FiPlus, FiTrash2 } from 'react-icons/fi';
import { useFieldArray, useForm } from 'react-hook-form';

import { CREATE_POLL } from '../api/polls';
import {
  applyTestPrefix,
  errorMessage,
  newIdempotencyKey,
} from '../utils/format';

const DEFAULT_VALUES = {
  question: '',
  options: [{ text: '' }, { text: '' }],
  durationMinutes: 5,
  addPrefix: true,
};

export function CreatePollForm({ channelId, authorId, onCreated }) {
  const toast = useToast();
  const [formError, setFormError] = useState('');
  const idempotencyKey = useRef(newIdempotencyKey());
  const {
    register,
    control,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm({ defaultValues: DEFAULT_VALUES });
  const { fields, append, remove } = useFieldArray({
    control,
    name: 'options',
  });
  const [createPoll, { loading }] = useMutation(CREATE_POLL);

  if (!channelId || !authorId) {
    return (
      <Alert status="warning" rounded="xl">
        <AlertIcon />
        <AlertDescription fontSize="sm">
          Configura el ID del canal y el ID del usuario para crear encuestas.
        </AlertDescription>
      </Alert>
    );
  }

  const onSubmit = async (values) => {
    setFormError('');
    const question = applyTestPrefix(values.question, values.addPrefix);
    const options = values.options
      .map((option) => option.text.trim())
      .filter(Boolean);

    if (options.length < 2) {
      setFormError('Agrega al menos dos alternativas.');
      return;
    }

    const normalized = options.map((option) => option.toLowerCase());
    if (new Set(normalized).size !== normalized.length) {
      setFormError('Las alternativas no pueden repetirse.');
      return;
    }

    try {
      await createPoll({
        variables: {
          input: {
            channelId,
            authorId,
            question,
            options,
            durationMinutes: Number(values.durationMinutes),
          },
          idempotencyKey: idempotencyKey.current,
        },
      });
      idempotencyKey.current = newIdempotencyKey();
      reset(DEFAULT_VALUES);
      toast({
        title: 'Encuesta creada',
        description: 'El anuncio se publicará en el canal mediante Messages.',
        status: 'success',
        duration: 4000,
        isClosable: true,
      });
      onCreated?.();
    } catch (error) {
      setFormError(errorMessage(error));
      toast({
        title: 'No se pudo crear la encuesta',
        description: errorMessage(error),
        status: 'error',
        duration: 6000,
        isClosable: true,
      });
    }
  };

  return (
    <Box
      as="form"
      onSubmit={handleSubmit(onSubmit)}
      bg="white"
      borderWidth="1px"
      borderColor="gray.200"
      rounded="xl"
      p={5}
    >
      <HStack mb={4}>
        <Box color="brand.500">
          <FiBarChart2 />
        </Box>
        <Box>
          <Text fontWeight="semibold" fontSize="sm">
            Nueva encuesta
          </Text>
          <Text fontSize="xs" color="gray.500">
            Se crea en Polls y se anuncia en este canal.
          </Text>
        </Box>
      </HStack>

      {formError ? (
        <Alert status="error" rounded="lg" mb={4}>
          <AlertIcon />
          <AlertDescription fontSize="sm">{formError}</AlertDescription>
        </Alert>
      ) : null}

      <VStack spacing={4} align="stretch">
        <FormControl isInvalid={Boolean(errors.question)}>
          <FormLabel fontSize="sm">Pregunta</FormLabel>
          <Input
            placeholder="¿Qué opción prefieres?"
            {...register('question', {
              required: 'La pregunta es obligatoria.',
              maxLength: {
                value: 300,
                message: 'Usa como máximo 300 caracteres.',
              },
            })}
          />
          {errors.question ? (
            <Text mt={1} fontSize="xs" color="red.500">
              {errors.question.message}
            </Text>
          ) : null}
        </FormControl>

        <FormControl>
          <FormLabel fontSize="sm">Alternativas</FormLabel>
          <VStack spacing={2} align="stretch">
            {fields.map((field, index) => (
              <HStack key={field.id} align="flex-start">
                <Box flex="1">
                  <Input
                    size="sm"
                    placeholder={`Alternativa ${index + 1}`}
                    {...register(`options.${index}.text`, {
                      maxLength: {
                        value: 120,
                        message: 'Máximo 120 caracteres.',
                      },
                    })}
                  />
                  {errors.options?.[index]?.text ? (
                    <Text mt={1} fontSize="xs" color="red.500">
                      {errors.options[index].text.message}
                    </Text>
                  ) : null}
                </Box>
                <IconButton
                  aria-label={`Eliminar alternativa ${index + 1}`}
                  icon={<FiTrash2 />}
                  size="sm"
                  variant="ghost"
                  colorScheme="red"
                  isDisabled={fields.length <= 2}
                  onClick={() => remove(index)}
                />
              </HStack>
            ))}
          </VStack>
          <Button
            mt={2}
            size="xs"
            variant="ghost"
            leftIcon={<FiPlus />}
            isDisabled={fields.length >= 10}
            onClick={() => append({ text: '' })}
          >
            Agregar alternativa
          </Button>
          <FormHelperText fontSize="xs">
            Entre 2 y 10 alternativas. No se permiten repetidas.
          </FormHelperText>
        </FormControl>

        <FormControl isInvalid={Boolean(errors.durationMinutes)}>
          <FormLabel fontSize="sm">Duración (minutos)</FormLabel>
          <Input
            type="number"
            min={1}
            max={1440}
            size="sm"
            {...register('durationMinutes', {
              required: 'Indica la duración.',
              min: { value: 1, message: 'Mínimo 1 minuto.' },
              max: { value: 1440, message: 'Máximo 1440 minutos.' },
            })}
          />
          {errors.durationMinutes ? (
            <Text mt={1} fontSize="xs" color="red.500">
              {errors.durationMinutes.message}
            </Text>
          ) : null}
        </FormControl>

        <Checkbox
          size="sm"
          {...register('addPrefix')}
          defaultChecked
        >
          Agregar prefijo [TEST-UI] a la pregunta
        </Checkbox>

        <Button
          type="submit"
          leftIcon={<FiBarChart2 />}
          isLoading={loading}
          loadingText="Creando…"
        >
          Crear encuesta
        </Button>
      </VStack>
    </Box>
  );
}
