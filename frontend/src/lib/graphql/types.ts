export type GraphqlError = {
  message: string;
  path?: Array<string | number>;
  extensions?: {
    code?: string;
    service?: string;
    status?: number;
    [key: string]: unknown;
  };
};

export type GraphqlResponse<TData> = {
  data?: TData | null;
  errors?: GraphqlError[];
  extensions?: Record<string, unknown>;
  httpStatus: number;
};

export type User = { id: string; displayName: string };
export type Channel = { id: string; name: string };

export type Reaction = {
  id: string;
  messageId: string;
  userId: string;
  reactionType: string;
  createdAt: string | null;
};

export type ReactionSummary = { reactionType: string; count: number };
export type MessageReactions = {
  messageId: string;
  totalReactions: number;
  summary: ReactionSummary[];
  reactions: Reaction[];
};

export type Message = {
  id: string;
  channelId: string;
  authorId: string;
  content: string;
  createdAt: string;
  author: User | null;
  reactions: MessageReactions | null;
};

export type PollOption = {
  optionId: string;
  position: number;
  text: string;
  voteCount: number;
};

export type Poll = {
  pollId: string;
  channelId: string;
  authorId: string;
  question: string;
  options: PollOption[];
  status: string;
  durationMinutes: number;
  closesAt: string;
  createdAt: string;
  closedAt: string | null;
  totalVotes: number;
  creationError: string | null;
};

export type Vote = {
  pollId: string;
  voterId: string;
  optionId: string;
  castAt: string;
};

export type SearchMessage = {
  id: string;
  channelId: string;
  authorId: string;
  content: string;
  createdAt: string;
  editedAt: string | null;
  has: string[];
  mentions: string[];
  links: string[];
  highlights: string[];
};

export type SearchMessagesResult = {
  totalResults: number;
  messages: SearchMessage[];
};

export type SearchMessagesInput = {
  content?: string;
  authorIds?: string[];
  channelIds?: string[];
  mentions?: string[];
  has?: Array<"LINK" | "MENTION">;
  minDate?: string;
  maxDate?: string;
  sortBy?: "TIMESTAMP" | "RELEVANCE";
  sortOrder?: "ASC" | "DESC";
  limit?: number;
  offset?: number;
};
