// Two panels on iPad and on iPhone in landscape, like Total Commander: the right panel is the target
// for Copy and Move (F5/F6), accepts drops from the left panel, and Swap exchanges the two.
// Included inside SooveeViewController.
#if !TARGET_OS_TV

- (void)setupSecondPanel:(UIStackView *)body {
    self.otherPeer=@"";self.otherPath=[NSUserDefaults.standardUserDefaults stringForKey:@"otherPath"]?:@"/";self.otherEntries=@[];
    self.otherContainer=[UIStackView new];self.otherContainer.axis=UILayoutConstraintAxisVertical;self.otherContainer.spacing=8;self.otherContainer.hidden=YES;
    self.otherHeader=[UIStackView new];self.otherHeader.axis=UILayoutConstraintAxisVertical;self.otherHeader.spacing=6;
    [self.otherContainer addArrangedSubview:self.otherHeader];
    UICollectionLayoutListConfiguration *config=[[UICollectionLayoutListConfiguration alloc]initWithAppearance:UICollectionLayoutListAppearanceInsetGrouped];config.backgroundColor=UIColor.clearColor;
    UICollectionViewCompositionalLayout *layout=[[UICollectionViewCompositionalLayout alloc]initWithSectionProvider:^NSCollectionLayoutSection *(NSInteger index,id<NSCollectionLayoutEnvironment> environment){
        NSCollectionLayoutSection *section=[NSCollectionLayoutSection sectionWithListConfiguration:config layoutEnvironment:environment];section.contentInsetsReference=UIContentInsetsReferenceNone;section.contentInsets=NSDirectionalEdgeInsetsMake(0,0,24,0);return section;}];
    self.otherCollection=[[UICollectionView alloc]initWithFrame:CGRectZero collectionViewLayout:layout];self.otherCollection.backgroundColor=UIColor.clearColor;self.otherCollection.delegate=self;
    self.otherCollection.dropDelegate=self;
    __weak SooveeViewController *weakSelf=self;
    UICollectionViewCellRegistration *cells=[UICollectionViewCellRegistration registrationWithCellClass:UICollectionViewListCell.class configurationHandler:^(UICollectionViewListCell *cell,NSIndexPath *indexPath,NSString *name){
        NSDictionary *item=nil;for(NSDictionary *entry in weakSelf.otherEntries)if([entry[@"name"] isEqual:name])item=entry;
        UIListContentConfiguration *content=[UIListContentConfiguration subtitleCellConfiguration];content.text=name;content.secondaryText=item?[weakSelf itemDetail:item]:nil;content.secondaryTextProperties.color=UIColor.secondaryLabelColor;
        content.image=[UIImage systemImageNamed:item?[weakSelf itemSymbol:item]:@"doc"];content.imageProperties.tintColor=[item[@"directory"] boolValue]?Accent():UIColor.secondaryLabelColor;
        content.imageProperties.maximumSize=CGSizeMake(32,32);content.imageProperties.reservedLayoutSize=CGSizeMake(32,32);cell.contentConfiguration=content;
        UIBackgroundConfiguration *background=[UIBackgroundConfiguration listGroupedCellConfiguration];background.backgroundColor=Surface();cell.backgroundConfiguration=background;
        cell.accessories=[item[@"directory"] boolValue]?@[[UICellAccessoryDisclosureIndicator new]]:@[];}];
    self.otherSource=[[UICollectionViewDiffableDataSource alloc]initWithCollectionView:self.otherCollection cellProvider:^UICollectionViewCell *(UICollectionView *view,NSIndexPath *indexPath,NSString *name){return [view dequeueConfiguredReusableCellWithRegistration:cells forIndexPath:indexPath item:name];}];
    [self.otherContainer addArrangedSubview:self.otherCollection];
    [body addArrangedSubview:self.otherContainer];
    [self.otherContainer.widthAnchor constraintEqualToAnchor:self.filesContainer.widthAnchor].active=YES;   // two equal panels
    // Left panel: drag files to the right panel or to another app.
    self.filesCollection.dragDelegate=self;self.filesCollection.dragInteractionEnabled=YES;
}

- (BOOL)twoPanels { return [self.screen isEqual:@"files"]&&self.view.bounds.size.width>=700; }
- (void)updatePanels {
    // iPhone in landscape is short: leave the height to the files, settings stay reachable from Overview.
    BOOL shortScreen=self.view.bounds.size.height<500;self.brand.hidden=shortScreen;self.status.hidden=shortScreen;
    BOOL two=[self twoPanels];BOOL was=!self.otherContainer.hidden;self.otherContainer.hidden=!two;
    if(two&&!was)[self showOtherFiles];
}
- (void)viewWillTransitionToSize:(CGSize)size withTransitionCoordinator:(id<UIViewControllerTransitionCoordinator>)coordinator {
    [super viewWillTransitionToSize:size withTransitionCoordinator:coordinator];
    [coordinator animateAlongsideTransition:nil completion:^(id<UIViewControllerTransitionCoordinatorContext> context){[self updatePanels];[self updateSelectionUI];}];
}

- (NSString *)deviceName:(NSString *)peer { if(!peer.length)return T(@"This device");for(NSDictionary *device in self.state[@"peers"])if([device[@"id"] isEqual:peer])return device[@"name"];return peer; }
- (void)showOtherFiles {
    NSString *peer=self.otherPeer,*path=self.otherPath;[self buildOtherHeader];
    [self call:peer.length?@"browse":@"browse_local_path" args:peer.length?@[peer,path]:@[path] then:^(NSString *json){if(![self.otherPath isEqual:path]||![self.otherPeer isEqual:peer])return;
        id values=[NSJSONSerialization JSONObjectWithData:[json dataUsingEncoding:NSUTF8StringEncoding] options:0 error:nil];NSMutableArray *entries=[([values isKindOfClass:NSArray.class]?values:@[]) mutableCopy];
        [entries sortUsingComparator:^NSComparisonResult(NSDictionary *a,NSDictionary *b){BOOL ad=[a[@"directory"] boolValue],bd=[b[@"directory"] boolValue];if(ad!=bd)return ad?NSOrderedAscending:NSOrderedDescending;return [a[@"name"] localizedStandardCompare:b[@"name"]];}];
        self.otherEntries=entries;NSDiffableDataSourceSnapshot *snapshot=[NSDiffableDataSourceSnapshot new];[snapshot appendSectionsWithIdentifiers:@[@"other"]];
        NSMutableOrderedSet *names=[NSMutableOrderedSet new];for(NSDictionary *item in entries)if([item[@"name"] isKindOfClass:NSString.class])[names addObject:item[@"name"]];
        [snapshot appendItemsWithIdentifiers:names.array];[self.otherSource applySnapshotUsingReloadData:snapshot];[self buildOtherHeader];}];
}
- (void)openOther:(NSString *)path peer:(NSString *)peer {
    self.otherPath=path;self.otherPeer=peer?:@"";if(!self.otherPeer.length)[NSUserDefaults.standardUserDefaults setObject:path forKey:@"otherPath"];[self showOtherFiles];
}
- (void)buildOtherHeader {
    for(UIView *view in self.otherHeader.arrangedSubviews){[self.otherHeader removeArrangedSubview:view];[view removeFromSuperview];}
    NSString *path=self.otherPath;BOOL root=[path isEqual:@"/"];
    UILabel *label=[self textLabel:T(@"Target panel") style:UIFontTextStyleFootnote weight:UIFontWeightSemibold color:Accent()];
    // Location menu: this device, paired devices, favorites.
    NSMutableArray *places=[NSMutableArray arrayWithObject:[UIAction actionWithTitle:T(@"This device") image:[UIImage systemImageNamed:@"iphone"] identifier:nil handler:^(UIAction *a){[self openOther:@"/" peer:@""];}]];
    for(NSDictionary *device in self.state[@"peers"])[places addObject:[UIAction actionWithTitle:device[@"name"] image:[UIImage systemImageNamed:@"desktopcomputer"] identifier:nil handler:^(UIAction *a){[self openOther:@"/" peer:device[@"id"]];}]];
    for(NSDictionary *place in [self places:@"favorites"])[places addObject:[UIAction actionWithTitle:place[@"name"] image:[UIImage systemImageNamed:@"star"] identifier:nil handler:^(UIAction *a){[self openOther:place[@"path"] peer:place[@"peer"]];}]];
    UIButton *location=[self headerTool:@"externaldrive" label:T(@"Location") menu:[UIMenu menuWithChildren:places] action:nil];
    UIButton *swap=[self headerTool:@"arrow.left.arrow.right" label:T(@"Swap panels") menu:nil action:^{[self swapPanels];}];
    UIButton *up=[self headerTool:@"arrow.up" label:T(@"Parent folder") menu:nil action:^{[self openOther:path.stringByDeletingLastPathComponent peer:self.otherPeer];}];up.enabled=!root;
    UIStackView *top=[[UIStackView alloc]initWithArrangedSubviews:@[label,[UIView new],up,location,swap]];top.spacing=8;top.alignment=UIStackViewAlignmentCenter;[self.otherHeader addArrangedSubview:top];
    UILabel *title=[self textLabel:root?[self deviceName:self.otherPeer]:path.lastPathComponent style:UIFontTextStyleTitle2 weight:UIFontWeightBold color:UIColor.labelColor];title.numberOfLines=1;[self.otherHeader addArrangedSubview:title];
    UILabel *where=[self textLabel:[NSString stringWithFormat:@"%@ · %@",[self deviceName:self.otherPeer],path] style:UIFontTextStyleFootnote weight:UIFontWeightRegular color:UIColor.secondaryLabelColor];where.numberOfLines=1;where.lineBreakMode=NSLineBreakByTruncatingHead;[self.otherHeader addArrangedSubview:where];
}
- (void)swapPanels {
    NSString *path=self.path,*peer=self.peer;
    self.path=self.otherPath;self.peer=self.otherPeer;self.otherPath=path;self.otherPeer=peer;
    self.filter=@"";self.searchQuery=nil;[self showFiles];[self showOtherFiles];
}
- (void)otherSelected:(NSIndexPath *)indexPath {
    [self.otherCollection deselectItemAtIndexPath:indexPath animated:YES];
    NSString *name=[self.otherSource itemIdentifierForIndexPath:indexPath];NSDictionary *item=nil;for(NSDictionary *entry in self.otherEntries)if([entry[@"name"] isEqual:name])item=entry;
    if([item[@"directory"] boolValue])[self openOther:[self.otherPath stringByAppendingPathComponent:name] peer:self.otherPeer];
}

// F5/F6: copy or move the selection (or the given names) into the right panel's folder.
- (void)copyToOther:(BOOL)moving names:(NSArray *)names {
    if(!names.count){[self showError:T(@"Choose files or folders first.")];return;}
    if([self.otherPath isEqual:@"/"]&&!self.otherPeer.length){[self showError:T(@"Open a folder in the target panel first.")];return;}
    if(moving&&(self.peer.length||self.otherPeer.length)){[self showError:T(@"Moving between devices is not available yet. Copy, verify, then delete the originals.")];return;}
    NSMutableArray *paths=[NSMutableArray new];for(NSString *name in names)[paths addObject:[self.path stringByAppendingPathComponent:name]];
    NSString *target=self.otherPeer,*folder=self.otherPath,*source=self.peer;
    UIAlertController *confirm=[UIAlertController alertControllerWithTitle:T(moving?@"Move":@"Copy") message:[NSString stringWithFormat:@"%@\n↓\n%@ · %@",[[names valueForKey:@"lastPathComponent"] componentsJoinedByString:@"\n"],[self deviceName:target],folder] preferredStyle:UIAlertControllerStyleAlert];
    [confirm addAction:[UIAlertAction actionWithTitle:T(@"Cancel") style:UIAlertActionStyleCancel handler:nil]];
    UIAlertAction *go=[UIAlertAction actionWithTitle:T(moving?@"Move":@"Copy") style:UIAlertActionStyleDefault handler:^(UIAlertAction *a){[self runTransfer:paths source:source target:target folder:folder moving:moving];}];
    [confirm addAction:go];confirm.preferredAction=go;[self presentViewController:confirm animated:YES completion:nil];
}

#pragma mark Drag and drop

- (NSArray<UIDragItem *> *)collectionView:(UICollectionView *)view itemsForBeginningDragSession:(id<UIDragSession>)session atIndexPath:(NSIndexPath *)indexPath {
    if(view!=self.filesCollection)return @[];
    NSString *name=[self.filesSource itemIdentifierForIndexPath:indexPath];NSDictionary *item=self.entryByName[name];if(!item||[self.path isEqual:@"/"])return @[];
    NSString *file=[self localPathFor:item];
    NSItemProvider *provider=file&&![item[@"directory"] boolValue]?[[NSItemProvider alloc]initWithContentsOfURL:[NSURL fileURLWithPath:file]]:[NSItemProvider new];   // files can also go to other apps
    provider.suggestedName=name.lastPathComponent;
    UIDragItem *drag=[[UIDragItem alloc]initWithItemProvider:provider];drag.localObject=name;
    return @[drag];
}
- (NSArray<UIDragItem *> *)collectionView:(UICollectionView *)view itemsForAddingToDragSession:(id<UIDragSession>)session atIndexPath:(NSIndexPath *)indexPath point:(CGPoint)point {
    return [self collectionView:view itemsForBeginningDragSession:session atIndexPath:indexPath];
}
- (BOOL)collectionView:(UICollectionView *)view canHandleDropSession:(id<UIDropSession>)session {
    return view==self.otherCollection&&session.localDragSession!=nil;
}
- (UICollectionViewDropProposal *)collectionView:(UICollectionView *)view dropSessionDidUpdate:(id<UIDropSession>)session withDestinationIndexPath:(NSIndexPath *)indexPath {
    if(view!=self.otherCollection||!session.localDragSession)return [[UICollectionViewDropProposal alloc]initWithDropOperation:UIDropOperationForbidden];
    return [[UICollectionViewDropProposal alloc]initWithDropOperation:UIDropOperationCopy intent:UICollectionViewDropIntentUnspecified];
}
- (void)collectionView:(UICollectionView *)view performDropWithCoordinator:(id<UICollectionViewDropCoordinator>)coordinator {
    NSMutableArray *names=[NSMutableArray new];for(id<UICollectionViewDropItem> item in coordinator.items)if([item.dragItem.localObject isKindOfClass:NSString.class])[names addObject:item.dragItem.localObject];
    [self copyToOther:NO names:names];
}

#pragma mark Keyboard

- (NSArray<UIKeyCommand *> *)keyCommands {
    if(![self.screen isEqual:@"files"]||self.presentedViewController)return @[];
    NSMutableArray *commands=[NSMutableArray new];
    void (^add)(NSString *,NSString *,UIKeyModifierFlags,SEL)=^(NSString *title,NSString *input,UIKeyModifierFlags flags,SEL action){
        UIKeyCommand *command=[UIKeyCommand commandWithTitle:T(title) image:nil action:action input:input modifierFlags:flags propertyList:nil];command.wantsPriorityOverSystemBehavior=YES;[commands addObject:command];};
    add(@"Copy to target panel",UIKeyInputF5,0,@selector(keyCopy));
    add(@"Move to target panel",UIKeyInputF6,0,@selector(keyMove));
    add(@"Delete",@"\b",UIKeyModifierCommand,@selector(keyDelete));
    add(@"Select all",@"a",UIKeyModifierCommand,@selector(keySelectAll));
    add(@"Refresh",@"r",UIKeyModifierCommand,@selector(keyRefresh));
    add(@"New folder",@"n",UIKeyModifierCommand|UIKeyModifierShift,@selector(keyNewFolder));
    add(@"Parent folder",UIKeyInputUpArrow,UIKeyModifierCommand,@selector(keyParent));
    add(@"Swap panels",@"\t",UIKeyModifierControl,@selector(keySwap));
    return commands;
}
- (BOOL)canBecomeFirstResponder { return YES; }
- (void)keyCopy { if([self twoPanels])[self copyToOther:NO names:self.selection.allObjects];else if(self.selection.count)[self chooseDestination:NO]; }
- (void)keyMove { if([self twoPanels])[self copyToOther:YES names:self.selection.allObjects];else if(self.selection.count)[self chooseDestination:YES]; }
- (void)keyDelete { if(self.selection.count&&![self.path isEqual:@"/"])[self deleteSelection]; }
- (void)keySelectAll { [self.selection addObjectsFromArray:self.entryByName.allKeys];self.selectionMode=YES;[self reloadVisibleFiles];[self updateSelectionUI]; }
- (void)keyRefresh { [self showFiles];if([self twoPanels])[self showOtherFiles]; }
- (void)keyNewFolder { if(![self.path isEqual:@"/"])[self editItem:nil]; }
- (void)keyParent { if(![self.path isEqual:@"/"])[self openFolder:self.path.stringByDeletingLastPathComponent]; }
- (void)keySwap { if([self twoPanels])[self swapPanels]; }
#endif
