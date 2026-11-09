import { ApolloLink, Observable } from '@apollo/client';

export const DEMO_CHANNEL_ID = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
export const DEMO_USER_ID = '11111111-1111-4111-8111-111111111111';
const DEMO_OTHER_USER_ID = '22222222-2222-4222-8222-222222222222';

const DEMO_STATE_KEY = 'polls-ui:demo-state-v3';

function newId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function isoOffset({ minutes = 0, hours = 0 } = {}) {
  return new Date(
    Date.now() + minutes * 60_000 + hours * 3_600_000,
  ).toISOString();
}

function seedState() {
  return {
    version: 3,
    polls: [
      {
        pollId: '33333333-3333-4333-8333-333333333333',
        channelId: DEMO_CHANNEL_ID,
        authorId: DEMO_USER_ID,
        question: '¿Qué tecnología prefieres para el frontend?',
        options: [
          {
            optionId: '33333333-3333-4333-8333-333333333301',
            position: 0,
            text: 'React',
            voteCount: 2,
          },
          {
            optionId: '33333333-3333-4333-8333-333333333302',
            position: 1,
            text: 'Vue',
            voteCount: 1,
          },
          {
            optionId: '33333333-3333-4333-8333-333333333303',
            position: 2,
            text: 'Angular',
            voteCount: 0,
          },
        ],
        status: 'open',
        durationMinutes: 60,
        closesAt: isoOffset({ hours: 1 }),
        createdAt: isoOffset({ minutes: -25 }),
        closedAt: null,
        totalVotes: 3,
        creationError: null,
        voters: [DEMO_OTHER_USER_ID],
      },
      {
        pollId: '44444444-4444-4444-8444-444444444444',
        channelId: DEMO_CHANNEL_ID,
        authorId: DEMO_USER_ID,
        question: '¿Qué día prefieres para la reunión?',
        options: [
          {
            optionId: '44444444-4444-4444-8444-444444444401',
            position: 0,
            text: 'Martes',
            voteCount: 3,
          },
          {
            optionId: '44444444-4444-4444-8444-444444444402',
            position: 1,
            text: 'Jueves',
            voteCount: 2,
          },
        ],
        status: 'closed',
        durationMinutes: 5,
        closesAt: isoOffset({ minutes: -60 }),
        createdAt: isoOffset({ minutes: -120 }),
        closedAt: isoOffset({ minutes: -60 }),
        totalVotes: 5,
        creationError: null,
        voters: [],
      },
    ],
  };
}

function loadState() {
  try {
    const raw = globalThis.localStorage?.getItem(DEMO_STATE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      if (
        parsed?.version === 3 &&
        Array.isArray(parsed.polls) &&
        parsed.polls.every((poll) => Array.isArray(poll.options))
      ) {
        return parsed;
      }
    }
  } catch {
    // Si localStorage no está disponible, se usa el estado en memoria.
  }

  const state = seedState();
  saveState(state);
  return state;
}

function saveState(state) {
  try {
    globalThis.localStorage?.setItem(DEMO_STATE_KEY, JSON.stringify(state));
  } catch {
    // El modo demo sigue funcionando sin persistencia.
  }
}

function publicPoll(poll) {
  const { voters: _voters, ...visiblePoll } = poll;
  return {
    __typename: 'Poll',
    ...visiblePoll,
    options: poll.options.map((option) => ({
      __typename: 'PollOption',
      ...option,
    })),
  };
}

function fail(message) {
  throw new Error(message);
}

export function executeDemoOperation({ operationName, variables = {} }) {
  const state = loadState();

  switch (operationName) {
    case 'GatewayHealth':
      return {
        health: { __typename: 'Health', status: 'demo', version: 'demo' },
      };

    case 'Polls':
      return {
        polls: state.polls
          .filter((poll) => poll.channelId === variables.channelId)
          .map(publicPoll),
      };

    case 'GetPoll': {
      const poll =
        state.polls.find((item) => item.pollId === variables.id) || null;
      return { poll: poll ? publicPoll(poll) : null };
    }

    case 'CreatePoll': {
      const input = variables.input ?? {};
      const question = String(input.question ?? '').trim();
      const options = (input.options ?? [])
        .map((option) => String(option).trim())
        .filter(Boolean);

      if (!question) fail('La pregunta es obligatoria.');
      if (options.length < 2) fail('Agrega al menos dos alternativas.');
      if (options.length > 10) fail('Máximo 10 alternativas.');
      if (
        new Set(options.map((option) => option.toLowerCase())).size !==
        options.length
      ) {
        fail('Las alternativas no pueden repetirse.');
      }

      const durationMinutes = Number(input.durationMinutes ?? 5);
      const poll = {
        pollId: newId(),
        channelId: input.channelId,
        authorId: input.authorId,
        question,
        options: options.map((text, position) => ({
          optionId: newId(),
          position,
          text,
          voteCount: 0,
        })),
        status: 'open',
        durationMinutes,
        closesAt: isoOffset({ minutes: durationMinutes }),
        createdAt: new Date().toISOString(),
        closedAt: null,
        totalVotes: 0,
        creationError: null,
        voters: [],
      };

      state.polls.push(poll);
      saveState(state);
      return { createPoll: publicPoll(poll) };
    }

    case 'Vote': {
      const poll = state.polls.find(
        (item) => item.pollId === variables.pollId,
      );
      if (!poll) fail('La encuesta no existe.');
      if (poll.status !== 'open') fail('La encuesta no está abierta.');
      if (!Array.isArray(poll.voters)) poll.voters = [];
      if (poll.voters.includes(variables.voterId)) {
        fail('Ya registraste un voto en esta encuesta.');
      }
      const option = poll.options.find(
        (item) => item.optionId === variables.optionId,
      );
      if (!option) fail('La alternativa no existe.');

      option.voteCount += 1;
      poll.totalVotes = (poll.totalVotes ?? 0) + 1;
      poll.voters.push(variables.voterId);
      saveState(state);
      return {
        vote: {
          __typename: 'Vote',
          pollId: poll.pollId,
          voterId: variables.voterId,
          optionId: option.optionId,
          castAt: new Date().toISOString(),
        },
      };
    }

    case 'ClosePoll': {
      const poll = state.polls.find(
        (item) => item.pollId === variables.pollId,
      );
      if (!poll) fail('La encuesta no existe.');
      if (poll.authorId !== variables.authorId) {
        fail('Solo el autor puede cerrar la encuesta.');
      }
      if (poll.status === 'closed') fail('La encuesta ya está cerrada.');

      poll.status = 'closed';
      poll.closedAt = new Date().toISOString();
      saveState(state);
      return { closePoll: publicPoll(poll) };
    }

    default:
      fail(`El modo demo no implementa la operación ${operationName}.`);
  }
}

export const demoLink = new ApolloLink(
  (operation) =>
    new Observable((observer) => {
      const timeout = setTimeout(() => {
        try {
          observer.next({
            data: executeDemoOperation({
              operationName: operation.operationName,
              variables: operation.variables,
            }),
          });
          observer.complete();
        } catch (error) {
          observer.next({ errors: [{ message: error.message }] });
          observer.complete();
        }
      }, 120);

      return () => clearTimeout(timeout);
    }),
);

export function resetDemoState() {
  try {
    const storage = globalThis.localStorage;
    if (storage) {
      const keys = [];
      for (let index = 0; index < storage.length; index += 1) {
        keys.push(storage.key(index));
      }
      keys
        .filter((key) => key?.startsWith('polls-ui:demo-'))
        .forEach((key) => storage.removeItem(key));
    }
  } finally {
    globalThis.location?.reload();
  }
}
