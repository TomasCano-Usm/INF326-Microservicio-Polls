import { Box, Button, Heading, Text } from '@chakra-ui/react';
import { FiArrowLeft } from 'react-icons/fi';
import { Link as RouterLink } from 'react-router-dom';

export default function NotFound() {
  return (
    <Box
      bg="white"
      borderWidth="1px"
      borderColor="gray.200"
      rounded="xl"
      px={6}
      py={16}
      textAlign="center"
    >
      <Text fontSize="6xl" fontWeight="800" color="brand.200" lineHeight="1">
        404
      </Text>
      <Heading size="lg" mt={4}>
        Página no encontrada
      </Heading>
      <Text mt={2} color="gray.500">
        La ruta que buscas no existe en esta interfaz.
      </Text>
      <Button
        mt={6}
        as={RouterLink}
        to="/"
        leftIcon={<FiArrowLeft />}
        variant="outline"
      >
        Volver al inicio
      </Button>
    </Box>
  );
}
