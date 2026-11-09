import { Box, Flex, Heading, Spacer, Text } from '@chakra-ui/react';

export function PageHeader({ title, description, action }) {
  return (
    <Flex
      align={{ base: 'flex-start', md: 'center' }}
      direction={{ base: 'column', md: 'row' }}
      gap={4}
      mb={8}
    >
      <Box>
        <Heading size="lg" letterSpacing="-0.02em">
          {title}
        </Heading>
        {description ? (
          <Text mt={1} color="gray.500" fontSize="sm" maxW="3xl">
            {description}
          </Text>
        ) : null}
      </Box>
      <Spacer />
      {action}
    </Flex>
  );
}
