import { gql } from '@apollo/client';

export const POLL_FIELDS = gql`
  fragment PollFields on Poll {
    pollId
    channelId
    authorId
    question
    options {
      optionId
      position
      text
      voteCount
    }
    status
    durationMinutes
    closesAt
    createdAt
    closedAt
    totalVotes
    creationError
  }
`;

export const LIST_POLLS = gql`
  query Polls($channelId: ID!) {
    polls(channelId: $channelId) {
      ...PollFields
    }
  }
  ${POLL_FIELDS}
`;

export const GET_POLL = gql`
  query GetPoll($id: ID!) {
    poll(id: $id) {
      ...PollFields
    }
  }
  ${POLL_FIELDS}
`;

export const CREATE_POLL = gql`
  mutation CreatePoll($input: CreatePollInput!, $idempotencyKey: String) {
    createPoll(input: $input, idempotencyKey: $idempotencyKey) {
      ...PollFields
    }
  }
  ${POLL_FIELDS}
`;

export const VOTE = gql`
  mutation Vote($pollId: ID!, $voterId: ID!, $optionId: ID!) {
    vote(pollId: $pollId, voterId: $voterId, optionId: $optionId) {
      pollId
      voterId
      optionId
      castAt
    }
  }
`;

export const CLOSE_POLL = gql`
  mutation ClosePoll($pollId: ID!, $authorId: ID!) {
    closePoll(pollId: $pollId, authorId: $authorId) {
      ...PollFields
    }
  }
  ${POLL_FIELDS}
`;
