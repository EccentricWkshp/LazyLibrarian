import { QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router';
import Blocklist from 'Activity/Blocklist/Blocklist';
import History from 'Activity/History/History';
import Queue from 'Activity/Queue/Queue';
import AddNew from 'AddNew/AddNew';
import AuthorDetails from 'Author/Details/AuthorDetails';
import AuthorIndex from 'Author/Index/AuthorIndex';
import ErrorBoundary from 'Components/ErrorBoundary';
import Link from 'Components/Link/Link';
import { Alert } from 'Components/Misc';
import Page from 'Components/Page/Page';
import PageContent from 'Components/Page/PageContent';
import PageContentBody from 'Components/Page/PageContentBody';
import BookDetails from 'Library/Books/BookDetails';
import BookIndex from 'Library/Books/BookIndex';
import ComicDetails from 'Library/Comics/ComicDetails';
import ComicIndex from 'Library/Comics/ComicIndex';
import MagazineDetails from 'Library/Magazines/MagazineDetails';
import MagazineIndex from 'Library/Magazines/MagazineIndex';
import PastIssues from 'Library/Magazines/PastIssues';
import RecentIssues from 'Library/Magazines/RecentIssues';
import Reader from 'Library/Reader/Reader';
import SeriesDetails from 'Library/Series/SeriesDetails';
import SeriesIndex from 'Library/Series/SeriesIndex';
import Backups from 'System/Backup/Backups';
import Events from 'System/Events/Events';
import LogFiles from 'System/LogFiles/LogFiles';
import Status from 'System/Status/Status';
import Tasks from 'System/Tasks/Tasks';
import Updates from 'System/Updates/Updates';
import { urlBase } from 'Utilities/api';
import Connect from 'Settings/Connect/Connect';
import Profiles from 'Settings/Profiles/Profiles';
import DownloadClients from 'Settings/Sections/DownloadClients';
import Filters from 'Settings/Sections/Filters';
import General from 'Settings/Sections/General';
import Indexers from 'Settings/Sections/Indexers';
import Languages from 'Settings/Sections/Languages';
import MediaManagement from 'Settings/Sections/MediaManagement';
import Metadata from 'Settings/Sections/Metadata';
import Tools from 'Settings/Sections/Tools';
import UI from 'Settings/Sections/UI';
import Settings from 'Settings/Settings';
import CutoffUnmet from 'Wanted/CutoffUnmet/CutoffUnmet';
import Missing from 'Wanted/Missing/Missing';
import BookSearch from 'Wanted/Search/BookSearch';
import queryClient from './queryClient';
import { useServerEvents } from './serverEvents';

function NotFound() {
  return (
    <PageContent title="Not Found">
      <PageContentBody>
        <Alert kind="warning">
          There's no page here. <Link to="/home">Go to the library</Link>
        </Alert>
      </PageContentBody>
    </PageContent>
  );
}

function App() {
  useServerEvents();

  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter basename={urlBase() || '/'}>
          <Page>
            <Routes>
              <Route path="/activity" element={<Navigate to="/activity/queue" replace={true} />} />
              <Route path="/activity/queue" element={<Queue />} />
              <Route path="/activity/history" element={<History />} />
              <Route path="/activity/blocklist" element={<Blocklist />} />
              <Route path="/wanted" element={<Navigate to="/wanted/missing" replace={true} />} />
              <Route path="/wanted/missing" element={<Missing />} />
              <Route path="/wanted/search" element={<BookSearch />} />
              <Route path="/wanted/cutoffunmet" element={<CutoffUnmet />} />
              <Route path="/settings" element={<Settings />} />
              <Route path="/settings/mediamanagement" element={<MediaManagement />} />
              <Route path="/settings/general" element={<General />} />
              <Route path="/settings/ui" element={<UI />} />
              <Route path="/settings/profiles" element={<Profiles />} />
              <Route path="/settings/connect" element={<Connect />} />
              <Route path="/settings/indexers" element={<Indexers />} />
              <Route path="/settings/downloadclients" element={<DownloadClients />} />
              <Route path="/settings/metadata" element={<Metadata />} />
              <Route path="/settings/filters" element={<Filters />} />
              <Route path="/settings/languages" element={<Languages />} />
              <Route path="/settings/tools" element={<Tools />} />
              <Route path="/add" element={<Navigate to="/add/new" replace={true} />} />
              <Route path="/add/new" element={<AddNew key="book" />} />
              <Route path="/authors" element={<AuthorIndex />} />
              <Route path="/author/:authorId" element={<AuthorDetails />} />
              <Route path="/books" element={<BookIndex key="ebook" mediaType="ebook" />} />
              <Route path="/audio" element={<BookIndex key="audiobook" mediaType="audiobook" />} />
              <Route path="/book/:bookId" element={<BookDetails />} />
              <Route path="/manage" element={<BookIndex key="manage" manage={true} />} />
              <Route path="/magazines" element={<MagazineIndex />} />
              <Route path="/magazines/add" element={<AddNew key="magazine" kind="magazine" />} />
              <Route path="/magazines/recent" element={<RecentIssues key="magazine" mediaType="magazine" />} />
              <Route path="/magazines/pastissues" element={<PastIssues />} />
              <Route path="/magazine" element={<MagazineDetails />} />
              <Route path="/comics" element={<ComicIndex />} />
              <Route path="/comics/add" element={<AddNew key="comic" kind="comic" />} />
              <Route path="/comics/recent" element={<RecentIssues key="comic" mediaType="comic" />} />
              <Route path="/comic/:comicId" element={<ComicDetails />} />
              <Route path="/read/:kind/:itemId" element={<Reader />} />
              <Route path="/series" element={<SeriesIndex />} />
              <Route path="/series/:seriesId" element={<SeriesDetails />} />
              <Route path="/system" element={<Navigate to="/system/status" replace={true} />} />
              <Route path="/system/status" element={<Status />} />
              <Route path="/system/tasks" element={<Tasks />} />
              <Route path="/system/backup" element={<Backups />} />
              <Route path="/system/updates" element={<Updates />} />
              <Route path="/system/events" element={<Events />} />
              <Route path="/system/logs/files" element={<LogFiles />} />
              <Route path="*" element={<NotFound />} />
            </Routes>
          </Page>
        </BrowserRouter>
      </QueryClientProvider>
    </ErrorBoundary>
  );
}

export default App;
