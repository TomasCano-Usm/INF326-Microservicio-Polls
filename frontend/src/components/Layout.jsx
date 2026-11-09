import {
  Box,
  Button,
  CloseButton,
  Drawer,
  DrawerContent,
  DrawerOverlay,
  Flex,
  HStack,
  Icon,
  IconButton,
  Link,
  Spacer,
  Text,
  VStack,
  useDisclosure,
} from '@chakra-ui/react';
import {
  FiAlertTriangle,
  FiBarChart2,
  FiInfo,
  FiMenu,
} from 'react-icons/fi';
import {
  Link as RouterLink,
  Outlet,
  useLocation,
} from 'react-router-dom';

import { resetDemoState } from '../api/demoLink';
import { DEMO_MODE } from '../config';
import { usePollsContext } from '../context/PollsContext';
import { HealthBadge } from './HealthBadge';
import { shortId } from '../utils/format';

const NAV_ITEMS = [
  { label: 'Encuestas', route: '/', icon: FiBarChart2 },
];

function SidebarBody({ onClose }) {
  const location = useLocation();
  const { channelId, userId } = usePollsContext();

  const isActive = (route) =>
    route === '/'
      ? location.pathname === '/' || location.pathname.startsWith('/encuestas')
      : location.pathname.startsWith(route);

  return (
    <Flex direction="column" h="100%" bg="white">
      <Flex
        h="20"
        align="center"
        px={5}
        borderBottomWidth="1px"
        borderColor="gray.100"
      >
        <HStack spacing={3}>
          <Flex
            w={9}
            h={9}
            align="center"
            justify="center"
            borderRadius="lg"
            bg="brand.500"
            color="white"
          >
            <Icon as={FiBarChart2} boxSize={5} />
          </Flex>
          <Box>
            <Text fontWeight="700" lineHeight="1">
              Polls
            </Text>
            <Text fontSize="xs" color="gray.500">
              Microservicio de encuestas
            </Text>
          </Box>
        </HStack>
        <Spacer />
        {onClose ? (
          <CloseButton display={{ base: 'flex', md: 'none' }} onClick={onClose} />
        ) : null}
      </Flex>

      <VStack align="stretch" spacing={1} p={4}>
        <Text
          px={3}
          pb={1}
          fontSize="2xs"
          fontWeight="bold"
          color="gray.400"
          textTransform="uppercase"
          letterSpacing="wider"
        >
          Navegación
        </Text>
        {NAV_ITEMS.map((item) => (
          <Link
            key={item.route}
            as={RouterLink}
            to={item.route}
            onClick={onClose}
            display="flex"
            alignItems="center"
            gap={3}
            px={3}
            py={2.5}
            borderRadius="lg"
            fontWeight={isActive(item.route) ? 'semibold' : 'medium'}
            color={isActive(item.route) ? 'brand.700' : 'gray.600'}
            bg={isActive(item.route) ? 'brand.50' : 'transparent'}
            _hover={{ bg: 'gray.50', color: 'gray.900', textDecoration: 'none' }}
          >
            <Icon as={item.icon} boxSize={4} />
            <Text fontSize="sm">{item.label}</Text>
          </Link>
        ))}
      </VStack>

      <Spacer />

      <Box p={4} borderTopWidth="1px" borderColor="gray.100">
        <Text
          fontSize="2xs"
          fontWeight="bold"
          color="gray.400"
          textTransform="uppercase"
          letterSpacing="wider"
          mb={2}
        >
          Contexto
        </Text>
        <VStack align="stretch" spacing={2}>
          <Box p={2.5} bg="gray.50" rounded="md">
            <Text fontSize="2xs" color="gray.400">
              Canal
            </Text>
            <Text fontSize="xs" fontWeight="semibold" fontFamily="mono" noOfLines={1}>
              {channelId ? shortId(channelId, 14) : 'Sin configurar'}
            </Text>
          </Box>
          <Box p={2.5} bg="gray.50" rounded="md">
            <Text fontSize="2xs" color="gray.400">
              Usuario
            </Text>
            <Text fontSize="xs" fontWeight="semibold" fontFamily="mono" noOfLines={1}>
              {userId ? shortId(userId, 14) : 'Sin configurar'}
            </Text>
          </Box>
        </VStack>
      </Box>
    </Flex>
  );
}

export default function Layout() {
  const { isOpen, onOpen, onClose } = useDisclosure();

  return (
    <Box minH="100vh" bg="gray.50">
      <Box
        position="fixed"
        left={0}
        top={0}
        w="64"
        h="100vh"
        borderRightWidth="1px"
        borderColor="gray.200"
        display={{ base: 'none', md: 'block' }}
        zIndex="docked"
      >
        <SidebarBody />
      </Box>

      <Drawer isOpen={isOpen} placement="left" onClose={onClose}>
        <DrawerOverlay />
        <DrawerContent>
          <SidebarBody onClose={onClose} />
        </DrawerContent>
      </Drawer>

      <Box ml={{ base: 0, md: 64 }}>
        <Flex
          h="20"
          align="center"
          px={{ base: 4, md: 8 }}
          bg="white"
          borderBottomWidth="1px"
          borderColor="gray.200"
          position="sticky"
          top={0}
          zIndex="docked"
        >
          <IconButton
            aria-label="Abrir menú"
            icon={<FiMenu />}
            variant="ghost"
            display={{ base: 'flex', md: 'none' }}
            onClick={onOpen}
            mr={2}
          />
          <Box>
            <Text fontWeight="semibold" lineHeight="1.2">
              Polls · Microservicio de encuestas
            </Text>
            <Text fontSize="xs" color="gray.500">
              {DEMO_MODE
                ? 'Demostración local sin gateway'
                : 'Interfaz conectada al API Gateway GraphQL'}
            </Text>
          </Box>
          <Spacer />
          <HStack spacing={3}>
            <HealthBadge />
          </HStack>
        </Flex>

        <Flex
          align="center"
          gap={2}
          px={{ base: 4, md: 8 }}
          py={2}
          bg={DEMO_MODE ? 'purple.50' : 'orange.50'}
          borderBottomWidth="1px"
          borderColor={DEMO_MODE ? 'purple.100' : 'orange.100'}
          flexWrap="wrap"
        >
          <Icon
            as={DEMO_MODE ? FiInfo : FiAlertTriangle}
            color={DEMO_MODE ? 'purple.500' : 'orange.500'}
            boxSize={3.5}
          />
          <Text fontSize="xs" color={DEMO_MODE ? 'purple.800' : 'orange.800'}>
            {DEMO_MODE ? (
              <>
                <strong>Modo demo:</strong> datos locales de ejemplo. No se
                envía nada al gateway.
              </>
            ) : (
              <>
                <strong>Entorno compartido:</strong> usa el prefijo{' '}
                <strong>[TEST-UI]</strong> en encuestas de prueba. No escribas
                datos sensibles.
              </>
            )}
          </Text>
          {DEMO_MODE ? (
            <Button
              ml="auto"
              size="xs"
              variant="ghost"
              colorScheme="purple"
              onClick={resetDemoState}
            >
              Reiniciar datos
            </Button>
          ) : null}
        </Flex>

        <Box as="main" p={{ base: 4, md: 8 }} maxW="7xl" mx="auto">
          <Outlet />
        </Box>
      </Box>
    </Box>
  );
}
